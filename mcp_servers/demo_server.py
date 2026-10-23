"""Demo MCP server exposing unit conversion and a vector database vendor directory."""

from mcp.server.mcpserver import MCPServer

server = MCPServer("aos-demo")

UNITS = {
    "ms": ("time", 0.001),
    "s": ("time", 1.0),
    "min": ("time", 60.0),
    "h": ("time", 3600.0),
    "b": ("data", 1.0),
    "kb": ("data", 1e3),
    "mb": ("data", 1e6),
    "gb": ("data", 1e9),
    "tb": ("data", 1e12),
    "m": ("length", 1.0),
    "km": ("length", 1000.0),
    "mi": ("length", 1609.344),
    "ft": ("length", 0.3048),
    "kg": ("mass", 1.0),
    "lb": ("mass", 0.45359237),
}

VENDORS = {
    "milvus": {
        "product": "Milvus",
        "maintainer": "Zilliz",
        "managed_offering": "Zilliz Cloud",
        "license": "Apache-2.0",
    },
    "qdrant": {
        "product": "Qdrant",
        "maintainer": "Qdrant",
        "managed_offering": "Qdrant Cloud",
        "license": "Apache-2.0",
    },
    "weaviate": {
        "product": "Weaviate",
        "maintainer": "Weaviate",
        "managed_offering": "Weaviate Cloud",
        "license": "BSD-3-Clause",
    },
    "chroma": {
        "product": "Chroma",
        "maintainer": "Chroma",
        "managed_offering": "Chroma Cloud",
        "license": "Apache-2.0",
    },
    "pgvector": {
        "product": "pgvector",
        "maintainer": "open-source community",
        "managed_offering": "available on most managed PostgreSQL services",
        "license": "PostgreSQL",
    },
}


@server.tool()
def unit_convert(value: float, from_unit: str, to_unit: str) -> dict:
    """Convert between units of time, data size, length or mass."""
    source, target = UNITS.get(from_unit.lower()), UNITS.get(to_unit.lower())
    if source is None or target is None:
        raise ValueError(f"unsupported unit; known units: {', '.join(sorted(UNITS))}")
    if source[0] != target[0]:
        raise ValueError(f"cannot convert {source[0]} to {target[0]}")
    return {"value": value * source[1] / target[1], "unit": to_unit}


@server.tool()
def company_lookup(names: list[str]) -> dict:
    """Look up maintainer, managed offering and license for vector database products."""
    found = {n: VENDORS[n.lower()] for n in names if n.lower() in VENDORS}
    missing = [n for n in names if n.lower() not in VENDORS]
    return {"vendors": found, "unknown": missing}


if __name__ == "__main__":
    server.run()
