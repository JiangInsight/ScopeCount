# Release validation

Validation on November 18, 2026 used a new directory populated only with the proposed release files. No research workspace data, compiled extension, or binary was copied. All 13 packages matched `requirements.txt`; builders fetched pinned dependencies and compiled three DuckDB operator families (four binaries, including the CRoaring-enabled retained build) and twelve native programs. Extension/path override variables were removed from the test environment.

| Check | Observed result |
|---|---|
| Source acquisition | Original Bakersfield RDS downloaded; raw SHA-256 and independent base-R oracle hash matched; 189,685 rows and 523 groups |
| Frozen input reconstruction | 79 core archive members and 5,833 operational members verified |
| All operational source counts | 2,290 tables, 10,315,079 rows, 50,104 recorded scope calls; all 172,408 returned scalar counts matched |
| Resident regression | 288 ordered full-result SQL comparisons, 240 weighted grouped answers, 664 binary tables/measurement schedules |
| Encoded files | 96 wide-score cases, full encoded/footer/group/slice matrix, 120 partial file-to-result cases |
| Retained implementation | Both builds passed empty input/slices, 64-bit boundaries, high-bit/duplicate predicates, shuffled/invalid row IDs, and result-cache reuse |
| Native models | 145,781 labeled slices; 64 canonical sequences with 91,850 schedules; 240 admission prefixes and 24 base activations |
| SQLShare replay | All 13 tables/27 logged requests; 675 resident and 675 file dispatched results checked |
| FCC replay | All 10,087,929 rows; original/shuffled resident layouts, four methods/four rounds each; five file methods/five rounds |
| Traffic replay | Bakersfield, ten resident methods/ten rounds; five file methods/five rounds; three row-degree/materialization controls/five rounds |
| Retained replay | Eight transport snapshots/406,995 rows/72 dispatches and eight CI snapshots/1,442,889 rows/2,880 dispatches; nine methods with matching cache policies |
| Factorial/segment controls | Six resident layouts at 524,288 rows, seven methods/seven rounds; two 1,048,576-row segment layouts, five methods/ten rounds |
| Frozen measurements | All 1,936,080 retained timing observations and their manifest hashes verified; all 9,020 grouped oracle tuples match 25 independent hashes |
| Frozen report | 25-query file totals and all 1,226-table CI repayment summaries regenerated successfully |

Machine-readable command records and logs are in [validation](../validation). New validation timings are not paper performance claims and were not written into the original trial archives. The release includes the paper's original unfavorable cases as well: informed SQL on SQLShare, short observed horizons, and memoized CI service remain in the comparisons.

The current validation did not redownload all 19 traffic-stop releases, rerun every five-repeat operational timing, rebuild the full 36-month flight input from the public ZIPs, or rerun every typed-source timing. Their frozen inputs/results, source acquisition, model code, drivers, and exact experiment commands are supplied. The Linux toolchain path remains untested.
