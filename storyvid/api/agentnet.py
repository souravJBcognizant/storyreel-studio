"""The agent network's topology for the Agents view, read from the HOCON the network runs from."""

from functools import lru_cache

from pyhocon import ConfigFactory

from .config import IMAGE_ENGINE, IMAGE_MODEL, LLM_MODEL, LLM_MODEL_ROUTINE, LLM_PROVIDER, LOCAL_MODE, PROJECT, VISION_ENGINE

NETWORK_FILE = PROJECT / "agents" / "registries" / "storyreel.hocon"

# What each coded tool runs on, so the graph can colour it.
TOOL_ENGINES = {
    "DescribeFirstFrame": VISION_ENGINE,
    "MakeReferenceSheets": IMAGE_ENGINE,
    "MakeKeyframes": IMAGE_ENGINE,  # each candidate is reviewed by the configured vision provider too
}


@lru_cache(maxsize=1)
def network() -> dict:
    cfg = ConfigFactory.parse_file(str(NETWORK_FILE))  # resolves ${?CLAUDE_MODEL} from the environment
    default_model = LLM_MODEL
    routine_default = cfg["routine_llm"]["model_name"]
    agents, tools = [], []
    unavailable = {"KeyframeArtist", "DescribeFirstFrame", "MakeReferenceSheets", "MakeKeyframes", "ChooseKeyframe"} if LOCAL_MODE else set()
    for spec in cfg["tools"]:
        name = spec["name"]
        if name in unavailable:
            continue
        description = spec["function"]["description"].strip()
        if "class" in spec:
            tools.append({"name": name, "description": description, "engine": TOOL_ENGINES.get(name, "local")})
        else:
            llm = spec.get("llm_config", None)
            agents.append({
                "name": name,
                "description": description,
                "model": LLM_MODEL_ROUTINE if llm and llm["model_name"] == routine_default else default_model,
                "tools": list(spec.get("tools", [])),
                "max_seconds": spec.get("max_execution_seconds", None),
            })  # fmt: skip
    return {"name": "storyreel", "front_man": agents[0]["name"], "agents": agents, "tools": tools,
            "llm_provider": LLM_PROVIDER, "local_mode": LOCAL_MODE,
            "image_model": None if LOCAL_MODE else (IMAGE_MODEL or None)}  # fmt: skip
