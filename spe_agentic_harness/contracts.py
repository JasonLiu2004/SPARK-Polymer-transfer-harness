"""Future research/RSI ports. Contracts only; not registered as executable tools."""
from typing import Any, Protocol


class DesignPort(Protocol):
    def propose_design(self, project_id: str, parent_version: str | None,
                       specification: dict[str, Any], evidence_ids: list[str]) -> dict: ...


class RecommendationPort(Protocol):
    def rank_candidates(self, project_id: str, design_versions: list[str],
                        objective_version: str, budget: dict) -> dict: ...


class ExperimentPort(Protocol):
    def plan_experiment(self, design_version: str, hypothesis_id: str, protocol: dict) -> dict: ...
    def record_observation(self, plan_id: str, observations: dict, artifact_ids: list[str]) -> dict: ...


class RSIPort(Protocol):
    def propose_revision(self, parent_policy_id: str, failure_event_ids: list[str],
                         changes: dict, training_snapshot_ids: list[str]) -> dict: ...
    def evaluate_revision(self, revision_id: str, benchmark_version: str,
                          baseline_policy_id: str, budget: dict) -> dict: ...
    def activate_revision(self, revision_id: str, evaluation_id: str,
                          acceptance_rule_version: str) -> dict: ...
    def rollback(self, project_id: str, previous_policy_id: str, reason: str) -> dict: ...
