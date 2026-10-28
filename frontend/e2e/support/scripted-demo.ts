import { expect, type Locator, type Page } from '@playwright/test';

export const demoAnswers = {
  introduction: /Hallo! Diese visuelle Demo folgt einem festen Skript\./,
  artifacts:
    /Dadurch ist die Validierung fehlgeschlagen und es wurde kein Artefakt erstellt\.[\s\S]*Sende noch eine Nachricht, um einen Fehlerzustand zu sehen\./,
  completion: 'Diese Demo ist abgeschlossen. Lade die Seite neu, um von vorn zu beginnen.',
};

export const demoPrompts = {
  introduction: 'Bitte stelle die Demo vor.',
  artifacts: 'Zeige die Begrüßungen.',
  failure: 'Zeige den Fehlerzustand.',
  completion: 'Schließe die Demo ab.',
  blocked: 'Extra nach Abschluss',
  restart: 'Starte die Demo erneut.',
};

const greetingJson = JSON.stringify({ message: 'Hallo, Welt!' }, null, 2);
const greetingsJson = JSON.stringify(
  { messages: Array.from({ length: 30 }, (_, index) => `Hallo, Besucher ${index + 1}!`) },
  null,
  2,
);

interface ArtifactExpectation {
  name: string;
  content: string;
}

export const demoArtifacts: readonly ArtifactExpectation[] = [
  { name: 'Begrüßung', content: greetingJson },
  { name: 'Begrüßungen', content: greetingsJson },
];

interface HistoryExpectation {
  prompts: readonly string[];
  answers: readonly (string | RegExp)[];
  artifacts: readonly ArtifactExpectation[];
}

interface ToolCallExpectation {
  name: string;
  status: string;
}

export class ScriptedDemo {
  readonly title: Locator;
  readonly scriptedBadge: Locator;
  readonly landingPageLink: Locator;
  readonly composer: Locator;
  readonly send: Locator;
  readonly history: Locator;
  readonly prompts: Locator;
  readonly answers: Locator;
  readonly artifactAnswer: Locator;
  readonly greetings: Locator;
  readonly artifacts: Locator;
  readonly expandGreetings: Locator;
  readonly collapseGreetings: Locator;
  readonly showDetails: Locator;
  readonly hideDetails: Locator;
  readonly tools: Locator;
  readonly generationError: Locator;
  readonly compatibilityError: Locator;
  readonly failureCommentary: Locator;
  readonly demoAction: Locator;
  readonly retry: Locator;

  constructor(page: Page) {
    const header = page.getByRole('banner');
    this.title = header.getByText('Visual Demo', { exact: true });
    this.scriptedBadge = header.getByText('Scripted', { exact: true });
    this.landingPageLink = header
      .getByRole('navigation', { name: 'Demo navigation' })
      .getByRole('link', { name: 'Demos', exact: true });
    this.composer = page.getByRole('textbox', { name: 'Nachricht', exact: true });
    this.send = page.getByRole('button', { name: 'Nachricht senden', exact: true });
    this.history = page.getByRole('log');
    this.prompts = this.history.getByRole('article', {
      name: 'Nachricht des Benutzers',
      exact: true,
    });
    this.answers = this.history.getByRole('article', {
      name: 'Antwort des Assistenten',
      exact: true,
    });
    this.artifactAnswer = this.answers.nth(1);
    this.greetings = this.history.getByRole('article', { name: 'Begrüßungen', exact: true });
    this.artifacts = this.history
      .getByRole('article')
      .filter({ has: page.getByRole('heading', { level: 3 }) });
    this.expandGreetings = this.greetings.getByRole('button', {
      name: 'Mehr anzeigen',
      exact: true,
    });
    this.collapseGreetings = this.greetings.getByRole('button', {
      name: 'Weniger anzeigen',
      exact: true,
    });
    this.showDetails = this.artifactAnswer.getByRole('button', {
      name: 'Details anzeigen',
      exact: true,
    });
    this.hideDetails = this.artifactAnswer.getByRole('button', {
      name: 'Details ausblenden',
      exact: true,
    });
    this.tools = this.history.getByRole('article', { name: 'Werkzeugaufruf', exact: true });
    this.generationError = this.history.getByText(
      'Die Antwort konnte nicht erstellt werden. Du kannst eine neue Nachricht senden.',
      { exact: true },
    );
    this.compatibilityError = this.history.getByText('App und Backend sind nicht kompatibel.', {
      exact: true,
    });
    this.failureCommentary = this.history
      .getByRole('article', { name: 'Zwischenmeldung des Assistenten', exact: true })
      .filter({ hasText: 'Ich beginne mit einer weiteren Antwort.' });
    this.demoAction = page.getByRole('button', {
      name: 'Demo-Aktion (ohne Funktion)',
      exact: true,
    });
    this.retry = page.getByRole('button', { name: /erneut|wiederholen|retry/i });
  }

  async returnToLandingPage(): Promise<void> {
    await this.landingPageLink.click();
  }

  async prepareMessage(message: string): Promise<void> {
    await this.composer.fill(message);
    await expect(this.send).toBeEnabled();
  }

  async sendMessage(message: string): Promise<void> {
    await this.prepareMessage(message);
    await this.send.click();
    await expect(this.composer).toHaveValue('');
  }

  async expectHistory(
    { prompts, answers, artifacts }: HistoryExpectation,
    options: { timeout?: number } = {},
  ): Promise<void> {
    await expect(this.prompts).toHaveText([...prompts], options);
    await expect(this.answers).toHaveText([...answers], options);
    await expect(this.artifacts).toHaveCount(artifacts.length, options);
    for (const [index, { name, content }] of artifacts.entries()) {
      const artifact = this.artifacts.nth(index);
      await expect(artifact).toHaveAccessibleName(name, options);
      await expect(artifact).toContainText(content, options);
    }
  }

  async expectToolCalls(
    calls: readonly ToolCallExpectation[],
    options: { timeout?: number } = {},
  ): Promise<void> {
    await expect(this.tools).toHaveCount(calls.length, options);
    for (const [index, { name, status }] of calls.entries()) {
      const call = this.tools.nth(index);
      await expect(call.locator('.name')).toHaveText(name, options);
      await expect(call.locator('.status')).toHaveText(status, options);
    }
  }
}

export function trackSubmittedPrompts(page: Page): readonly unknown[] {
  const prompts: unknown[] = [];
  page.on('request', (request) => {
    if (
      request.method() === 'POST' &&
      /^\/api\/v1\/agents\/visual-demo\/sessions\/[^/]+\/turns$/.test(
        new URL(request.url()).pathname,
      )
    ) {
      const payload: unknown = request.postDataJSON();
      prompts.push(
        typeof payload === 'object' && payload !== null && 'prompt' in payload
          ? payload.prompt
          : undefined,
      );
    }
  });
  return prompts;
}
