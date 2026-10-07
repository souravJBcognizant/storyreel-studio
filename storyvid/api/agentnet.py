"""The agent network's topology for the Agents view, read from the HOCON the network runs from."""

import os
from functools import lru_cache

from pyhocon import ConfigFactory

from .config import PROJECT

NETWORK_FILE = PROJECT / "agents" / "registries" / "storyreel.hocon"

# What each coded tool runs on, so the graph can colour it.
TOOL_ENGINES = {
    "DescribeFirstFrame": "claude",
    "MakeReferenceSheets": "openai",
    "MakeKeyframes": "openai",  # each candidate is reviewed by Claude too
}


@lru_cache(maxsize=1)
def network() -> dict:
    cfg = ConfigFactory.parse_file(str(NETWORK_FILE))  # resolves ${?CLAUDE_MODEL} from the environment
    default_model = cfg["llm_config"]["model_name"]
    agents, tools = [], []
    for spec in cfg["tools"]:
        name = spec["name"]
        description = spec["function"]["description"].strip()
        if "class" in spec:
            tools.append({"name": name, "description": description, "engine": TOOL_ENGINES.get(name, "local")})
        else:
            llm = spec.get("llm_config", None)
            agents.append({
                "name": name,
                "description": description,
                "model": llm["model_name"] if llm else default_model,
                "tools": list(spec.get("tools", [])),
                "max_seconds": spec.get("max_execution_seconds", None),
            })  # fmt: skip
    return {"name": "storyreel", "front_man": agents[0]["name"], "agents": agents, "tools": tools,
            "image_model": os.environ.get("OPENAI_IMAGE_MODEL")}  # fmt: skip
