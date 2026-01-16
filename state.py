from typing import Annotated, TypedDict, List, Optional
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages

class AgentState(TypedDict):
    # add_messages ensures new messages are appended to history
    messages: Annotated[list[BaseMessage], add_messages]
    file_paths: List[str]  # List of uploaded files
    active_worker: str     # 'sql', 'csv', 'db_chart_worker', or 'general'
    last_sql_query: Optional[str]  # Stores SQL query for chart generation
    chart_code_generated: Optional[bool]  # Flag to track if chart code was generated