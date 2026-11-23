"""Choose the primary forecast order before the next five years of SPE evidence are opened."""
from evidence import ROOT, verified
from evidence_order import constrained_tiers
from ordinal import positions


EXPOSURE = "exposure"
ORDINAL = "ordinal"
DEFAULT_RUN = "exposure_primary"
POLICIES = (EXPOSURE, ORDINAL)


def registered_policy(protocol):
    # Original sealed runs predate this field and contain the unconstrained order.
    policy = protocol.get("primary_ranking", ORDINAL)
    if policy not in POLICIES:
        raise ValueError(f"Unsupported primary ranking policy: {policy}")
    return policy


def select_policy(home, requested=None):
    prior = home / "protocol.json"
    if prior.exists():
        existing = registered_policy(verified(prior))
        if requested is not None and requested != existing:
            raise ValueError(f"{home.name} is registered as {existing}. Use a new --run-id for {requested}.")
        return existing
    return requested or EXPOSURE


def implementation_path(name, policy):
    if policy == ORDINAL and name in ("run.py", "memory.py"):
        return ROOT / "history" / "ordinal" / name
    return ROOT / name


def apply_exposure_policy(panel, preferences, cutoff):
    """Use only distinct historical DOI counts, last publication year, and the LLM's ordinal comparison."""
    flat = [name for tier in preferences for name in tier]
    if any(not tier for tier in preferences) or len(flat)!=len(panel) or set(flat)!=set(panel):
        raise ValueError("LLM tiers must cover each panel material exactly once")
    model_ranks = positions(preferences)
    evidence = {}
    for name, item in panel.items():
        count, latest = item["papers"], item["latest"]
        if type(count) is not int or count <= 0 or type(latest) is not int or not 0 < latest <= cutoff:
            raise ValueError(f"Invalid dated publication coverage for {name}")
        evidence[name] = {"source_count": count, "latest_source": latest, "rank_min": model_ranks[name][0]}
    return constrained_tiers(evidence)


def ranking_record(policy, preferences, panel, cutoff, pool):
    """Construct full, in-pool and LLM-only positions from the same cutoff panel."""
    if policy == EXPOSURE:
        tiers = apply_exposure_policy(panel, preferences, cutoff)
    elif policy == ORDINAL:
        tiers = preferences
    else:
        raise ValueError(f"Unsupported primary ranking policy: {policy}")
    all_ranks = positions(tiers)
    if set(all_ranks)!=set(panel) or not set(pool)<=set(panel):
        raise ValueError("Ranking or admission does not match the cutoff panel")
    return tiers, all_ranks, positions(tiers, pool), positions(preferences)
