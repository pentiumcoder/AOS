from aos.agents.specialists.base import SpecialistAgent


class WritingAgent(SpecialistAgent):
    name = "writing"
    description = "Turns other subtasks' findings into the written deliverable and can send it."
