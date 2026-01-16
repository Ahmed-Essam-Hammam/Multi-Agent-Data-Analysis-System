from langgraph.graph import StateGraph, END, START
from langgraph.prebuilt import ToolNode
from langchain_core.messages import AIMessage, ToolMessage
from state import AgentState
from nodes import supervisor_node, csv_worker_node, sql_worker_node, db_chart_worker_node
from tools import python_analyst, get_sql_tools, db_python_analyst


def create_workflow():
    workflow = StateGraph(AgentState)

    workflow.add_node("supervisor", supervisor_node)
    workflow.add_node("csv_worker", csv_worker_node)
    workflow.add_node("sql_worker", sql_worker_node)
    workflow.add_node("db_chart_worker", db_chart_worker_node)

    workflow.add_node("csv_tools", ToolNode([python_analyst]))
    workflow.add_node("db_chart_tools", ToolNode([db_python_analyst]))

    def call_sql_tools(state):
        db_file = next(f for f in state["file_paths"] if f.endswith(".db"))
        tools = get_sql_tools(db_file)

        tool_result = ToolNode(tools).invoke(state)

        return {
            "messages": tool_result["messages"],
            "last_sql_query": state.get("last_sql_query"),
        }

    workflow.add_node("sql_tools", call_sql_tools)

    # Start at supervisor
    workflow.add_edge(START, "supervisor")

    # Supervisor routes to workers or END
    workflow.add_conditional_edges(
        "supervisor",
        lambda state: state["active_worker"],
        {
            "csv_worker": "csv_worker",
            "sql_worker": "sql_worker",
            "general": END
        }
    )

    # CSV worker routing
    workflow.add_conditional_edges(
        "csv_worker",
        lambda state: "csv_tools" if (
            isinstance(state["messages"][-1], AIMessage) and 
            state["messages"][-1].tool_calls
        ) else END,
        {"csv_tools": "csv_tools", END: END}
    )
    workflow.add_edge("csv_tools", "csv_worker")

    # SQL worker routing
    def sql_router(state):
        last = state["messages"][-1]

        # If SQL worker wants to call tools, route to sql_tools
        if isinstance(last, AIMessage) and last.tool_calls:
            return "sql_tools"
        
        # If active_worker was changed to db_chart_worker, route there
        if state.get("active_worker") == "db_chart_worker":
            return "db_chart_worker"

        # Otherwise, we're done
        return END
    
    workflow.add_conditional_edges(
        "sql_worker",
        sql_router,
        {
            "sql_tools": "sql_tools",
            "db_chart_worker": "db_chart_worker", 
            END: END
        }
    )

    # After SQL tools execute, go back to sql_worker to decide next step
    workflow.add_edge("sql_tools", "sql_worker")

    # DB chart worker routing
    workflow.add_conditional_edges(
        "db_chart_worker",
        lambda state: "db_chart_tools" if (
            isinstance(state["messages"][-1], AIMessage) and 
            state["messages"][-1].tool_calls
        ) else END,
        {"db_chart_tools": "db_chart_tools", END: END}
    )

    # After chart tools execute, go back to db_chart_worker to summarize
    workflow.add_edge("db_chart_tools", "db_chart_worker")
    
    return workflow.compile()

app_graph = create_workflow()