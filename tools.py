import os 
import pandas as pd
import matplotlib.pyplot as plt
import sqlite3
from datetime import datetime
from langchain_core.tools import tool
from langchain_experimental.utilities import PythonREPL
from langchain_community.utilities import SQLDatabase
from langchain_community.agent_toolkits import SQLDatabaseToolkit
from config import llm

python_repl = PythonREPL()

@tool
def python_analyst(code: str, file_name: str):
    """
    Analyzes CSV data using Python. 'df' is pre-loaded.
    Always use print() to show your final answer.
    Executes Python code on a CSV file.
    Always returns a STRING.
    """
    try:
        # 1. Clean filename and path
        file_path = os.path.join("uploads", os.path.basename(file_name))
        charts_dir = "charts"
        os.makedirs(charts_dir, exist_ok=True)
        if not os.path.exists(file_path):
            return f"Error: {file_name} not found in uploads/."

        # 2. Force fresh load
        df = pd.read_csv(file_path)

        # 3. Isolated execution environment
        plt.switch_backend('Agg')

        # 4. Inject globals into REPL
        python_repl.globals = {"df": df, "pd": pd, "plt": plt}
        
        # 5. Execute
        result = python_repl.run(code)

        # 6. Detect any matplotlib figures and save them
        fig_path = None
        figs = [plt.figure(n) for n in plt.get_fignums()]
        if figs:
            base_name = os.path.splitext(os.path.basename(file_name))[0]
            fig_name = f"{base_name}_chart.png"
            fig_path = os.path.join(charts_dir, fig_name)
            figs[-1].savefig(fig_path)
            plt.close(figs[-1])

        # 7. Format textual output
        output_text = ""
        if isinstance(result, dict):
            output_text = str(result)
        elif isinstance(result, list):
            output_text = ", ".join(map(str, result))
        elif result and result.strip():
            output_text = str(result).strip()
        else:
            output_text = "Execution successful, but no result was printed. Please use print()."

        # 8. Append chart info if a figure was saved
        if fig_path:
            output_text += f"\n[Chart saved to {fig_path}]"

        return output_text.strip()

    except Exception as e:
        return f"Python Error: {str(e)}"
    

@tool
def db_python_analyst(code: str, db_file: str, sql_query: str):
    """
    Analyzes SQL query results using Python.
    Data is provided as rows + columns and loaded as DataFrame `df`.
    Always use print().
    Returns STRING.
    """
    try:
        # 1. Load data from database
        db_path = os.path.join("uploads", db_file)
        conn = sqlite3.connect(db_path)
        df = pd.read_sql_query(sql_query, conn)
        conn.close()

        print(f"DEBUG: Loaded {len(df)} rows from database")

        # 2. Setup charts directory
        charts_dir = "charts"
        os.makedirs(charts_dir, exist_ok=True)

        # 3. Setup matplotlib
        plt.switch_backend("Agg")
        python_repl.globals = {"df": df, "pd": pd, "plt": plt}

        # 4. Execute the code
        result = python_repl.run(code)

        # 5. Save any generated figures with unique timestamp
        fig_path = None
        figs = [plt.figure(n) for n in plt.get_fignums()]
        if figs:
            # Create unique filename with timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            db_name = os.path.splitext(db_file)[0]
            fig_name = f"{db_name}_chart_{timestamp}.png"
            fig_path = os.path.join(charts_dir, fig_name)
            
            # Save with high quality
            figs[-1].savefig(fig_path, dpi=150, bbox_inches='tight')
            plt.close(figs[-1])
            
            print(f"DEBUG: Chart saved to {fig_path}")

        # 6. Format output
        output = result.strip() if result else "Chart created successfully."
        if fig_path:
            # Use absolute path so user can find it easily
            abs_path = os.path.abspath(fig_path)
            output += f"\n\n📊 Chart saved to: {abs_path}"

        return output

    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        return f"Python Error: {str(e)}\n\nDetails:\n{error_details}"

    

def get_sql_tools(db_file: str):
    """Dynamically creates SQL tools for a specific uploaded database."""

    db_path = os.path.join("uploads", os.path.basename(db_file))

    if not os.path.exists(db_path):
        raise RuntimeError(f"Database file not found: {db_path}")

    db = SQLDatabase.from_uri(f"sqlite:///{db_path}", include_tables=None)
    toolkit = SQLDatabaseToolkit(db=db, llm=llm)
    tools = toolkit.get_tools()

    for t in tools:
        t.name = "sql_db_query"

    return tools