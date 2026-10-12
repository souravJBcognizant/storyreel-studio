"""The agent network's topology for the Agents view, read from the HOCON the network runs from."""

from functools import lru_cache

from pyhocon import ConfigFactory

from . import config

NETWORK_FILE = config.PROJECT / "agents" / "registries" / "storyreel.hocon"


@lru_cache(maxsize=1)
def network() -> dict:
    cfg = ConfigFactory.parse_file(str(NETWORK_FILE))  # resolves ${?CLAUDE_MODEL} from the environment
    default_model = config.LLM_MODEL
    routine_default = cfg["routine_llm"]["model_name"]
    tool_engines = {
        "DescribeFirstFrame": config.VISION_ENGINE,
        "MakeReferenceSheets": config.IMAGE_ENGINE,
        "MakeKeyframes": config.IMAGE_ENGINE,
    }
    agents, tools = [], []
    unavailable = {"KeyframeArtist", "DescribeFirstFrame", "MakeReferenceSheets", "MakeKeyframes", "ChooseKeyframe"} if config.LOCAL_MODE else set()
    for spec in cfg["tools"]:
        name = spec["name"]
        if name in unavailable:
            continue
        description = spec["function"]["description"].strip()
        if "class" in spec:
            tools.append({"name": name, "description": description, "engine": tool_engines.get(name, "local")})
        else:
            llm = spec.get("llm_config", None)
            agents.append({
                "name": name,
                "description": description,
                "model": config.LLM_MODEL_ROUTINE if llm and llm["model_name"] == routine_default else default_model,
                "tools": list(spec.get("tools", [])),
                "max_seconds": spec.get("max_execution_seconds", None),
            })  # fmt: skip
    return {"name": "storyreel", "front_man": agents[0]["name"], "agents": agents, "tools": tools,
            "llm_provider": config.LLM_PROVIDER, "local_mode": config.LOCAL_MODE,
            "image_model": None if config.LOCAL_MODE else (config.IMAGE_MODEL or None)}  # fmt: skip
