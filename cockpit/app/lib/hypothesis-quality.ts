import rawQuality from "../hypothesis-quality-data.json";

type DiagnosticProperty = {
  display_name_fr: string;
  family: string;
  property_id: string;
  public_hypothesis_eligible: boolean;
  semantic_role: string;
};

type HypothesisQualityData = {
  semanticRoles: {
    classification_complete: boolean;
    items: DiagnosticProperty[];
    property_count: number;
    public_allowed_roles: string[];
    role_counts: Record<string, number>;
    schema_version: string;
  };
  workspace: {
    diagnostic_properties: DiagnosticProperty[];
    diagnostics: {
      availability_bias: boolean;
      blocked_families: number;
      coverage: boolean;
      missing_values: boolean;
      partial_families: number;
      pre_match_unavailability: boolean;
      source_errors: boolean;
    };
    internal_controls: Array<{
      property_id: string;
      public_hypothesis_eligible: boolean;
      semantic_role: string;
      technical_rule: Record<string, unknown>;
    }>;
    legacy_public_false_hypothesis_branches_removed: number;
    live_writes: number;
    provider_calls: number;
    public_hypothesis_surface: boolean;
    schema_version: string;
    title_fr: string;
    workspace_path: string;
  };
};

const data = rawQuality as HypothesisQualityData;

if (
  !data.semanticRoles.classification_complete ||
  data.semanticRoles.items.length !== data.semanticRoles.property_count ||
  data.workspace.public_hypothesis_surface
) {
  throw new Error("HYPOTHESIS_QUALITY_CONTRACT_INVALID");
}

export const hypothesisSemanticRoles = data.semanticRoles;
export const hypothesisDataQualityWorkspace = data.workspace;
