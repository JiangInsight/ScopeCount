# ScopeCount: Exact Grouped Completeness Audits from Score Margins and Boundary Prefixes

ScopeCount uses known group sizes and score margins to recover exact completeness counts from boundary prefixes. The DuckDB extension reads Parquet validity information and returns one score per group.

## Run

64-bit Windows, Python 3.11–3.13 and Visual Studio C++ Build Tools. The build fetches the pinned DuckDB and CRoaring dependencies.

~~~powershell
python -m pip install -r requirements.txt
python build.py
python run_example.py
~~~

[Data](data) includes a grouped audit table and 1,300 file-query measurements comparing boundary prefixes, SQL, packed scores, dense rank and CRoaring.
