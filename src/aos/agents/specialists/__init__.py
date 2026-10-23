from aos.agents.specialists.analysis import AnalysisAgent
from aos.agents.specialists.base import SpecialistAgent
from aos.agents.specialists.code import CodeAgent
from aos.agents.specialists.research import ResearchAgent
from aos.agents.specialists.writing import WritingAgent

SPECIALIST_AGENTS: dict[str, type[SpecialistAgent]] = {
    agent.name: agent for agent in (ResearchAgent, AnalysisAgent, WritingAgent, CodeAgent)
}


def get_specialist(name: str) -> SpecialistAgent:
    try:
        return SPECIALIST_AGENTS[name]()
    except KeyError:
        raise KeyError(f"unknown specialist: {name}") from None


__all__ = ["SPECIALIST_AGENTS", "SpecialistAgent", "get_specialist"]
