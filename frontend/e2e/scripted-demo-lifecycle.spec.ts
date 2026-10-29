import { test, expect } from '@playwright/test';
import {
  ScriptedDemo,
  demoAnswers,
  demoPrompts,
  demoArtifacts,
  trackSubmittedPrompts,
} from './support/scripted-demo';

test.describe('Scripted demo integrated lifecycle', () => {
  test('completes the scripted conversation, retains intentional failures, blocks the extra submission, and resets on reload', async ({
    page,
  }) => {
    test.setTimeout(60_000);

    const demo = new ScriptedDemo(page);
    const submittedPrompts = trackSubmittedPrompts(page);
    const conversationPrompts = [
      demoPrompts.introduction,
      demoPrompts.artifacts,
      demoPrompts.failure,
      demoPrompts.completion,
    ];

    const conversationAnswers = [
      demoAnswers.introduction,
      demoAnswers.artifacts,
      demoAnswers.completion,
    ];

    await test.step('Initialize an empty scripted demo session', async () => {
      await page.goto('/demos/visual');
      await expect(demo.composer).toBeEditable();
      await expect(demo.history).toContainText(
        'Diese Demo folgt einem festen Skript ohne KI-Modell.',
      );
      await demo.expectHistory({ prompts: [], answers: [], artifacts: [] });
      await expect(demo.send).toBeDisabled();
    });

    await test.step('Receive the introduction without artifacts', async () => {
      await demo.sendMessage(demoPrompts.introduction);
      await demo.expectHistory(
        {
          prompts: conversationPrompts.slice(0, 1),
          answers: [demoAnswers.introduction],
          artifacts: [],
        },
        { timeout: 15_000 },
      );
      await expect(demo.composer).toBeEditable();
      expect(submittedPrompts).toEqual(conversationPrompts.slice(0, 1));
    });

    await test.step('Receive two greeting artifacts and retain the introduction', async () => {
      await demo.sendMessage(demoPrompts.artifacts);
      await demo.expectHistory(
        {
          prompts: conversationPrompts.slice(0, 2),
          answers: conversationAnswers.slice(0, 2),
          artifacts: demoArtifacts,
        },
        { timeout: 20_000 },
      );
      expect(submittedPrompts).toEqual(conversationPrompts.slice(0, 2));
    });

    await test.step('Expand and collapse the long artifact', async () => {
      await expect(demo.expandGreetings).toHaveAttribute('aria-expanded', 'false');
      await demo.expandGreetings.click();
      await expect(demo.collapseGreetings).toHaveAttribute('aria-expanded', 'true');
      await expect(demo.greetings).toContainText('Hallo, Besucher 30!');
      await demo.collapseGreetings.click();
      await expect(demo.expandGreetings).toHaveAttribute('aria-expanded', 'false');
      await demo.expectHistory({
        prompts: conversationPrompts.slice(0, 2),
        answers: conversationAnswers.slice(0, 2),
        artifacts: demoArtifacts,
      });
    });

    await test.step('Show and hide run details and verify tool outcomes', async () => {
      await demo.showDetails.click();
      await demo.expectToolCalls([
        { name: 'present_artifact', status: 'Abgeschlossen' },
        { name: 'present_artifact', status: 'Abgeschlossen' },
        { name: 'present_artifact', status: 'Fehlgeschlagen' },
      ]);
      await demo.hideDetails.click();
      await expect(demo.showDetails).toHaveAttribute('aria-expanded', 'false');
      await demo.expectHistory({
        prompts: conversationPrompts.slice(0, 2),
        answers: conversationAnswers.slice(0, 2),
        artifacts: demoArtifacts,
      });
    });

    await test.step('Retain commentary and previous content after the intentional failure', async () => {
      await demo.sendMessage(demoPrompts.failure);
      await expect(demo.generationError).toBeVisible({ timeout: 15_000 });
      await expect(demo.failureCommentary).toBeVisible();
      await demo.expectHistory({
        prompts: conversationPrompts.slice(0, 3),
        answers: conversationAnswers.slice(0, 2),
        artifacts: demoArtifacts,
      });
      expect(submittedPrompts).toEqual(conversationPrompts.slice(0, 3));
    });

    await test.step('The demo action is inert and leaves the next submission available', async () => {
      await demo.demoAction.click();
      await expect(demo.generationError).toBeVisible();
      await expect(demo.failureCommentary).toBeVisible();
      await demo.expectHistory({
        prompts: conversationPrompts.slice(0, 3),
        answers: conversationAnswers.slice(0, 2),
        artifacts: demoArtifacts,
      });
      await demo.prepareMessage(demoPrompts.completion);
      expect(submittedPrompts).toEqual(conversationPrompts.slice(0, 3));
    });

    await test.step('Complete the fourth turn despite the preceding failed run', async () => {
      await demo.send.click();
      await demo.expectHistory(
        { prompts: conversationPrompts, answers: conversationAnswers, artifacts: demoArtifacts },
        { timeout: 15_000 },
      );
      await expect(demo.failureCommentary).toBeVisible();
      expect(submittedPrompts).toEqual(conversationPrompts);
    });

    await test.step('Block the extra submission locally while preserving draft and history', async () => {
      await demo.prepareMessage(demoPrompts.blocked);
      await demo.send.click();
      await expect(demo.compatibilityError).toBeVisible();
      await expect(demo.composer).toHaveValue(demoPrompts.blocked);
      await expect(demo.send).toBeDisabled();
      await demo.expectHistory({
        prompts: conversationPrompts,
        answers: conversationAnswers,
        artifacts: demoArtifacts,
      });
      await expect(demo.failureCommentary).toBeVisible();
      await expect(demo.retry).toHaveCount(0);
      expect(submittedPrompts).toEqual(conversationPrompts);
    });

    await test.step('Reload into an empty session and restart at the introduction', async () => {
      await page.reload();
      await expect(demo.composer).toBeEditable();
      await expect(demo.composer).toHaveValue('');
      await demo.expectHistory({ prompts: [], answers: [], artifacts: [] });
      await expect(demo.compatibilityError).toHaveCount(0);
      await expect(demo.generationError).toHaveCount(0);
      await expect(demo.failureCommentary).toHaveCount(0);
      await demo.sendMessage(demoPrompts.restart);
      await demo.expectHistory(
        { prompts: [demoPrompts.restart], answers: [demoAnswers.introduction], artifacts: [] },
        { timeout: 15_000 },
      );
      expect(submittedPrompts).toEqual([...conversationPrompts, demoPrompts.restart]);
    });
  });
});
