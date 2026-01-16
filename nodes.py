import pandas as pd
import os
from langchain_core.messages import SystemMessage, ToolMessage, AIMessage, HumanMessage
from config import llm
from tools import python_analyst, get_sql_tools, db_python_analyst

def get_csv_metadata(file_path):
    """Helper to extract a tiny summary of a CSV to save tokens."""
    try:
        # Only read the first 7 rows to keep the prompt small
        df = pd.read_csv(file_path, nrows=7)
        summary = (
            f"File: {os.path.basename(file_path)}\n"
            f"Columns: {list(df.columns)}\n"
            f"Sample Data:\n{df.to_string(index=False)}"
        )
        return summary
    except Exception as e:
        return f"Error reading {file_path}: {str(e)}"

def supervisor_node(state):
    """Safely extracts text and routes the user based on query and files."""
    if not state.get("messages"):
        return {"active_worker": "general"}
    
    last_message = state["messages"][-1]

    if last_message.type == "assistant" and not last_message.tool_calls:
        return {"active_worker": "general"}
    
    content = last_message.content

    # Safe text extraction (Handles both strings and list-style content)
    text_query = " ".join([part.get("text", "") for part in content]) if isinstance(content, list) else (content or "")
    query = text_query.lower()
    files = state.get("file_paths", [])

    has_db = any(f.lower().endswith('.db') for f in files)
    has_csv = any(f.lower().endswith('.csv') for f in files)

    if has_db and any(word in query for word in ["sql", "database", "table", "query"]):
        return {"active_worker": "sql_worker"}
    elif has_csv:
        return {"active_worker": "csv_worker"}
    
    return {"active_worker": "general"}


def csv_worker_node(state):
    # Only get column names, NOT sample data, to prevent the 'dict' hallucination
    csv_files = [f for f in state.get("file_paths", []) if f.lower().endswith('.csv')]
    # Simpler metadata: just columns
    metadata = "\n".join([f"File: {f}" for f in csv_files])

    last_msg = state["messages"][-1]
    
    if isinstance(last_msg, ToolMessage):

        if not isinstance(last_msg.content, str):
            raise RuntimeError("Tool output is not a string. Tool normalization failed.")

        # Check if a chart was generated
        chart_path = None
        if "[Chart saved to" in last_msg.content:
            import re
            match = re.search(r"\[Chart saved to (.+?)\]", last_msg.content)
            if match:
                chart_path = match.group(1)

        prompt = f"""
        You are a data analyst.

        The following is the FINAL RESULT of a computation:
        {last_msg.content}

        TASK:
        - Summarize the answer and state it clearly.
        - If a chart was created, mention where it was saved.
        - DO NOT explain errors unless the text explicitly starts with "Error".
        - Respond in 1-2 sentences.
        """

        response = llm.invoke([SystemMessage(content=prompt)])
        
        # If there's a chart, append the path info to the response
        if chart_path:
            # Ensure the response includes the chart path in a format Streamlit can extract
            original_content = response.content
            if "Chart saved to:" not in original_content:
                response.content = f"{original_content}\n\n📊 Chart saved to: {chart_path}"
        
        return {"messages": [response]}
    else:
        # PHASE: CODE GENERATION
        # We explicitly tell it df is a PANDAS DATAFRAME
        prompt = f"""You are a Python Data Analyst. 
        Available Files: {metadata}
        
        TASK: {state['messages'][0].content}
        
        STRICT RULES (NO EXCEPTIONS):
        1. You MUST call the python_analyst tool.
        2. Decide which CSV file is relevant and use ONLY that file.
        3. The pandas DataFrame is already loaded as `df`.
        4. Use print() to output the final numeric/text result.
        5. DO NOT explain.
        6. DO NOT write Python code as plain text.
        7. Output ONLY a tool call.
        """
        agent = llm.bind_tools([python_analyst])

        # Important: We only pass the necessary history to avoid 'Context Pollution'
        messages = [SystemMessage(content=prompt)] + state["messages"]
        response = agent.invoke(messages)

        if not response.tool_calls:
            raise RuntimeError("CSV worker failed to call python_analyst tool.")

        return {"messages": [response]}

def sql_worker_node(state):
    """SQL Agent: Handles queries and detects chart intent."""
    db_file = next(f for f in state["file_paths"] if f.endswith('.db'))
    db_path = os.path.join("uploads", db_file)
    
    tools = get_sql_tools(db_path)
    agent = llm.bind_tools(tools)

    last_msg = state["messages"][-1]

    # Check if we just got tool results back
    if isinstance(last_msg, ToolMessage):
        user_query = state["messages"][0].content.lower()

        # Detect chart/visualization keywords
        chart_words = [
            "plot", "chart", "graph", "visualize", "draw",
            "histogram", "bar", "line", "scatter", "pie"
        ]

        has_chart_intent = any(w in user_query for w in chart_words)

        # Verify we have a stored SQL query
        if has_chart_intent and state.get("last_sql_query"):
            # Switch to chart worker instead of summarizing
            return {
                "active_worker": "db_chart_worker",
                "messages": state["messages"],
            }
        elif has_chart_intent and not state.get("last_sql_query"):
            # This shouldn't happen, but just in case
            return {
                "messages": state["messages"] + [
                    AIMessage(content="Error: Unable to generate chart - SQL query not found.")
                ]
            }

        # No chart intent - just summarize the SQL results
        prompt = "You have the query results. Summarize the answer for the user in a clear and concise way."
        response = llm.invoke([SystemMessage(content=prompt)] + state["messages"])
        return {"messages": [response]}

    # Initial query - generate SQL
    # First, check if this is a chart request
    user_query = state["messages"][0].content.lower()
    chart_words = [
        "plot", "chart", "graph", "visualize", "draw",
        "histogram", "bar", "line", "scatter", "pie"
    ]
    has_chart_intent = any(w in user_query for w in chart_words)

    # If it's a chart request, we need MORE data (not limited to 10 rows)
    limit_instruction = "Do NOT limit rows." if has_chart_intent else "Always limit rows to 10 unless a larger result is explicitly needed."

    prompt = f"""You are a SQL Expert.
    You are connected to the database: {db_file}

    TASK: {state['messages'][0].content}

    RULES:
    1. Always call the 'sql_db_query' tool.
    2. Inspect tables and columns first if needed.
    3. Execute queries to answer the user's request directly.
    4. ALWAYS use table aliases and fully qualify column names (e.g., p.UnitPrice, od.Quantity) to avoid ambiguity.
    5. Example: SELECT p.ProductName, SUM(od.UnitPrice * od.Quantity) FROM [Order Details] od JOIN Products p ON od.ProductID = p.ProductID
    6. Quote table or column names using square brackets [ ] if they contain spaces.
    7. {limit_instruction}
    8. Output ONLY a tool call, no explanations.
    """
    
    messages = [SystemMessage(content=prompt)] + state["messages"]
    response = agent.invoke(messages)

    updates = {"messages": [response]}

    # Store the SQL query for potential chart generation
    if isinstance(response, AIMessage) and response.tool_calls:
        sql_query = response.tool_calls[0]["args"]["query"]
        updates["last_sql_query"] = sql_query
        print(f"🔍 DEBUG: Stored SQL query: {sql_query}")

    return updates


def db_chart_worker_node(state):
    """
    Uses the previously generated SQL query to load data via pandas
    and generate charts using Python.
    """

    # 1️⃣ Retrieve stored SQL query
    sql_query = state.get("last_sql_query")
    print(f"🎨 DEBUG: Chart worker received SQL query: {sql_query}")
    print(f"🎨 DEBUG: chart_code_generated flag: {state.get('chart_code_generated')}")
    
    if not sql_query:
        raise RuntimeError("No SQL query found for chart generation.")

    # 2️⃣ Identify the DB file
    db_file = next(f for f in state["file_paths"] if f.endswith(".db"))

    last_msg = state["messages"][-1]
    
    print(f"🎨 DEBUG: Last message type: {type(last_msg).__name__}")

    # If we just executed the chart tool, summarize the result
    if isinstance(last_msg, ToolMessage) and state.get("chart_code_generated"):
        print(f"🎨 DEBUG: Processing chart tool result")
        prompt = f"""
        You are a data analyst.

        The following is the FINAL RESULT of chart generation:
        {last_msg.content}

        TASK:
        - Confirm that the chart was created successfully and tell the user where it was saved.
        - If there's an error, explain it clearly.
        - Keep it brief and helpful.
        """
        response = llm.invoke([SystemMessage(content=prompt)])
        return {"messages": [response], "chart_code_generated": False}

    # 3️⃣ Generate chart code (first time in chart worker)
    print(f"🎨 DEBUG: Generating chart code")
    
    prompt = f"""
You are a Python data visualization expert.

DATABASE: {db_file}
SQL QUERY: {sql_query}

The data from this SQL query will be loaded into a pandas DataFrame named `df`.

USER REQUEST: {state["messages"][0].content}

CRITICAL INSTRUCTIONS:
1. You MUST call the db_python_analyst tool - DO NOT respond with text.
2. The tool requires these THREE arguments:
   - code: Your matplotlib visualization code (string)
   - db_file: "{db_file}" (exact string)
   - sql_query: "{sql_query}" (exact string)
3. The DataFrame `df` is already loaded - DO NOT use pd.read_sql or connect to database.
4. Write ONLY matplotlib plotting code.
5. Use print() to output a confirmation message.
6. Example code structure:
   ```
   plt.figure(figsize=(10, 6))
   plt.hist(df['column_name'], bins=20)
   plt.xlabel('Label')
   plt.ylabel('Frequency')
   plt.title('Title')
   print('Histogram created successfully')
   ```

DO NOT explain anything. ONLY call the tool.
"""

    # 4️⃣ Bind the db_python_analyst tool
    agent = llm.bind_tools([db_python_analyst])

    # 5️⃣ Invoke agent
    messages = [SystemMessage(content=prompt)]
    response = agent.invoke(messages)
    
    print(f"🎨 DEBUG: Agent response type: {type(response).__name__}")
    print(f"🎨 DEBUG: Has tool_calls: {hasattr(response, 'tool_calls') and bool(response.tool_calls)}")
    if hasattr(response, 'tool_calls') and response.tool_calls:
        print(f"🎨 DEBUG: Tool call name: {response.tool_calls[0].get('name')}")

    if not response.tool_calls:
        raise RuntimeError(f"db_chart_worker failed to call db_python_analyst tool. Response: {response.content}")

    return {"messages": [response], "chart_code_generated": True}