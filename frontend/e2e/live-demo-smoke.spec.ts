import { test } from '@playwright/test';
import { LiveDemo } from './support/live-demo';

test.describe('Live demo real-provider smoke', () => {
  test('receives a text answer and completes a tool-assisted answer with an intermediate message', async ({
    page,
  }) => {
    test.setTimeout(120_000);
    const demo = new LiveDemo(page);

    await test.step('Open the live demo directly', async () => {
      await demo.goto();
    });

    await test.step('Receive a text-only model answer', async () => {
      const response = await demo.sendMessage(
        'Antworte bitte in einem kurzen Satz als normale Textantwort: Was ist ein Chatbot? Verwende für diese Antwort keine Werkzeuge.',
      );
      await response.expectFinalAnswer();
    });

    await test.step('Receive an intermediate message, successful tool call, and final answer', async () => {
      const response = await demo.sendMessage(
        'Bitte zeige mir ein kleines JSON-Beispiel mithilfe des verfügbaren Werkzeugs present_artifact. Sende zuerst eine kurze Zwischenmeldung an mich, was du gleich tun wirst. Rufe dann present_artifact mit type json und einem gültigen kleinen Beispiel auf, etwa Titel Beispiel und payload {"value":{"message":"Hallo"}}. Warte auf das Werkzeugergebnis und sende danach eine kurze eigenständige abschließende Antwort.',
      );
      await response.expectFinalAnswer();
      await response.showDetails();
      await response.expectIntermediateMessage();
      await response.expectSuccessfulToolCall('present_artifact');
    });
  });
});
