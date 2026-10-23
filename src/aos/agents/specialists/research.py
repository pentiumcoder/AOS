from aos.agents.specialists.base import SpecialistAgent


class ResearchAgent(SpecialistAgent):
    name = "research"
    description = "Finds external information and summarises it with source URLs."
