export interface IntegrationDemoArtifact {
  readonly type: 'integration-demo';
  readonly id: string;
  readonly headline: string;
  readonly payload: {
    readonly name: string;
    readonly description: string;
  };
}

export interface ChatDemoRendererContext {
  readonly $implicit: IntegrationDemoArtifact;
}
