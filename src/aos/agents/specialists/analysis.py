from aos.agents.specialists.base import SpecialistAgent


class AnalysisAgent(SpecialistAgent):
    name = "data_analysis"
    description = "Queries the analytics database and computes figures with Python."
