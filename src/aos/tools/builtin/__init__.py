from aos.tools.base import ToolSpec
from aos.tools.builtin.code_exec import CodeExecInput, CodeExecOutput, code_exec
from aos.tools.builtin.db_query import DbQueryInput, DbQueryOutput, db_query
from aos.tools.builtin.file_io import (
    FileDeleteInput,
    FileReadInput,
    FileWriteInput,
    file_delete,
    file_read,
    file_write,
)
from aos.tools.builtin.http_get import HttpGetInput, http_get
from aos.tools.builtin.send_email import SendEmailInput, send_email
from aos.tools.builtin.web_search import WebSearchInput, WebSearchOutput, web_search


def builtin_tools() -> list[ToolSpec]:
    return [
        ToolSpec(
            name="web_search",
            description="Search the web. Returns titles, URLs and snippets.",
            handler=web_search,
            input_model=WebSearchInput,
            output_model=WebSearchOutput,
            timeout_s=20,
        ),
        ToolSpec(
            name="http_get",
            description="Fetch a URL from an allowlisted domain and return its text.",
            handler=http_get,
            input_model=HttpGetInput,
            timeout_s=15,
        ),
        ToolSpec(
            name="file_read",
            description="Read a text file from this task's workspace.",
            handler=file_read,
            input_model=FileReadInput,
        ),
        ToolSpec(
            name="file_write",
            description="Write or append a text file in this task's workspace.",
            handler=file_write,
            input_model=FileWriteInput,
        ),
        ToolSpec(
            name="file_delete",
            description="Delete a file from this task's workspace. Requires approval.",
            handler=file_delete,
            input_model=FileDeleteInput,
            sensitive=True,
        ),
        ToolSpec(
            name="code_exec",
            description=(
                "Run a Python 3 script and return stdout. No network or project files; "
                "embed any data the script needs. Print results explicitly."
            ),
            handler=code_exec,
            input_model=CodeExecInput,
            output_model=CodeExecOutput,
            timeout_s=40,
        ),
        ToolSpec(
            name="db_query",
            description=(
                "Run one read-only SELECT against the analytics database. Table benchmarks "
                "has one row per vector database, named in the database column. Columns: "
                "database, dataset, vectors_millions, recall_at_10, p95_latency_ms, qps, "
                "index_build_minutes, monthly_cost_usd, license, source."
            ),
            handler=db_query,
            input_model=DbQueryInput,
            output_model=DbQueryOutput,
            timeout_s=15,
        ),
        ToolSpec(
            name="send_email",
            description=(
                "Send an email. Requires approval before it is sent. "
                "Use {{final_output}} in the body to include the final deliverable."
            ),
            handler=send_email,
            input_model=SendEmailInput,
            sensitive=True,
        ),
    ]
