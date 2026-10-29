import { expect, type Locator, type Page } from '@playwright/test';
import type {
  PresentedSession,
  PresentedTurn,
  PresentationPart,
} from '../../projects/chat-ui/conversation/generated/types.gen';
import {
  zPresentedSession,
  zSessionCreated,
} from '../../projects/chat-ui/conversation/generated/zod.gen';

export class LiveDemo {
  readonly title: Locator;
  readonly liveBadge: Locator;
  readonly landingPageLink: Locator;
  readonly composer: Locator;
  readonly send: Locator;
  private sessionUrl: string | undefined;

  constructor(private readonly page: Page) {
    const header = page.getByRole('banner');
    this.title = header.getByText('Live Demo', { exact: true });
    this.liveBadge = header.getByText('Live', { exact: true });
    this.landingPageLink = header
      .getByRole('navigation', { name: 'Demo navigation' })
      .getByRole('link', { name: 'Demos', exact: true });
    this.composer = page.getByRole('textbox', { name: 'Nachricht', exact: true });
    this.send = page.getByRole('button', { name: 'Nachricht senden', exact: true });
  }

  async goto(): Promise<void> {
    const created = this.page.waitForResponse(
      (response) =>
        response.request().method() === 'POST' &&
        new URL(response.url()).pathname === '/api/v1/agents/live-demo/sessions',
    );
    await this.page.goto('/demos/live');
    const response = await created;
    expect(response.status()).toBe(201);
    const session = zSessionCreated.parse(await response.json());
    this.sessionUrl = `${response.url()}/${encodeURIComponent(session.session_id)}`;
  }

  async sendMessage(message: string): Promise<LiveDemoResponse> {
    const previous = await this.readSession();
    const previousRuns = new Set(
      previous.history
        .filter((item) => item.part_kind === 'turn')
        .map((turn) => turn.lifecycle.run_id),
    );
    await this.composer.fill(message);
    await expect(this.send).toBeEnabled();
    await this.send.click();

    let turns: PresentedTurn[] = [];
    await expect
      .poll(
        async () => {
          const snapshot = await this.readSession();
          turns = snapshot.history.filter(
            (item): item is PresentedTurn =>
              item.part_kind === 'turn' && !previousRuns.has(item.lifecycle.run_id),
          );
          return turns.length > 0 && turns.every((turn) => turn.lifecycle.status !== 'running');
        },
        { message: 'The live model run finishes', timeout: 50_000 },
      )
      .toBe(true);
    expect(
      turns.map((turn) => turn.lifecycle.status),
      'The live model run succeeds',
    ).toEqual(turns.map(() => 'completed'));

    const prompt = this.page
      .getByRole('article', { name: 'Nachricht des Benutzers', exact: true })
      .filter({ hasText: message });
    const content = this.page
      .getByRole('log')
      .locator('.history-item')
      .filter({ has: prompt })
      .locator('~ .history-item');
    return new LiveDemoResponse(
      content,
      turns.flatMap((turn) => turn.parts),
    );
  }

  private async readSession(): Promise<PresentedSession> {
    if (this.sessionUrl === undefined)
      throw new Error('Open the live demo before submitting a message.');
    const response = await this.page.request.get(this.sessionUrl, {
      headers: { 'X-Application-User': 'demo:default' },
    });
    expect(response.status()).toBe(200);
    return zPresentedSession.parse(await response.json());
  }

  async returnToLandingPage(): Promise<void> {
    await this.landingPageLink.click();
  }
}

class LiveDemoResponse {
  private readonly answer: Locator;

  constructor(
    private readonly content: Locator,
    private readonly parts: readonly PresentationPart[],
  ) {
    this.answer = content
      .getByRole('article', { name: 'Antwort des Assistenten', exact: true })
      .last();
  }

  async expectFinalAnswer(): Promise<void> {
    expect(
      this.parts.some(
        (part) =>
          part.part_kind === 'text' && part.phase === 'final_answer' && /\S/.test(part.content),
      ),
      'The model supplies a nonempty final answer',
    ).toBe(true);
    await expect(this.answer.locator('.markdown')).toContainText(/\S/);
  }

  async showDetails(): Promise<void> {
    await this.answer.getByRole('button', { name: 'Details anzeigen', exact: true }).click();
  }

  async expectIntermediateMessage(): Promise<void> {
    expect(
      this.parts.some(
        (part) =>
          part.part_kind === 'text' && part.phase === 'commentary' && /\S/.test(part.content),
      ),
      'The model supplies a distinct nonempty intermediate message',
    ).toBe(true);
    const intermediate = this.content
      .getByRole('article', {
        name: 'Zwischenmeldung des Assistenten',
        exact: true,
      })
      .filter({ hasText: /\S/ })
      .first();
    await expect(intermediate).toBeVisible();
  }

  async expectSuccessfulToolCall(name: string): Promise<void> {
    expect(
      this.parts.some(
        (part) =>
          part.part_kind === 'tool-call' && part.tool_name === name && part.status === 'success',
      ),
      `The model successfully executes ${name}`,
    ).toBe(true);
    const tool = this.content
      .getByRole('article', { name: 'Werkzeugaufruf', exact: true })
      .filter({ hasText: name })
      .filter({ hasText: 'Abgeschlossen' })
      .first();
    await expect(tool).toBeVisible();
  }
}
