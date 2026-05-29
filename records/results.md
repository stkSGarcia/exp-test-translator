## Table 1: Tokens & Timing

| CP | Command | Start (UTC) | Duration | LLM Calls | Input | CC-1h | CC-5m | Cache Read | Output | Total |
| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | /opsx:propose | 2026-05-25 23:35:36 | 3m 18s | 25 | 29 | 23814 | 0 | 676130 | 9416 | 709389 |
| 1 | /opsx:propose | 2026-05-25 22:20:16 | 3m 04s | 6 | 8 | 9293 | 0 | 115244 | 776 | 125321 |
| 1 | /opsx:apply | 2026-05-25 23:39:22 | 20m 19s | 25 | 26 | 64561 | 0 | 1749112 | 48200 | 1861899 |
| 1 | /opsx:archive | 2026-05-25 23:59:58 | 6m 57s | 18 | 25 | 80695 | 12514 | 769037 | 3051 | 865322 |
| 2 | /opsx:propose | 2026-05-26 00:09:54 | 4m 43s | 27 | 31 | 42166 | 0 | 1009756 | 9401 | 1061354 |
| 2 | /opsx:apply | 2026-05-26 00:15:13 | 14m 28s | 33 | 34 | 39567 | 0 | 2300707 | 55429 | 2395737 |
| 2 | /opsx:archive | 2026-05-26 00:32:09 | 2m 41s | 21 | 27 | 85308 | 24644 | 1152422 | 3979 | 1266380 |
| 8 | /opsx:propose | 2026-05-29 00:41:22 | 3m 10s | 26 | 30 | 71676 | 0 | 1307255 | 8272 | 1387233 |
| 8 | /opsx:apply | 2026-05-29 00:46:33 | 37m 30s | 51 | 54 | 26721 | 0 | 5146988 | 15570 | 5189333 |
| 8 | /opsx:archive | 2026-05-29 01:24:10 | 5m 18s | 14 | 19 | 4104 | 8534 | 961397 | 3549 | 977603 |

**Per-checkpoint totals:**

| CP | LLM Calls | Input | CC-1h | CC-5m | Cache Read | Output | Total |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| **1** | 74 | 88 | 178363 | 12514 | 3309523 | 61443 | 3561931 |
| **2** | 81 | 92 | 167041 | 24644 | 4462885 | 68809 | 4723471 |
| **8** | 91 | 103 | 102501 | 8534 | 7415640 | 27391 | 7554169 |

## Table 2: LLM Call Breakdown & Latency

| CP | Command | LLM Calls | Tool-use stops | End-turn stops | Thinking calls | Avg Latency |
| ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | /opsx:propose | 25 | 24 | 1 | 8 | 6.2s |
| 1 | /opsx:propose | 6 | 6 | 0 | 2 | 2.8s |
| 1 | /opsx:apply | 25 | 23 | 1 | 5 | 24.3s |
| 1 | /opsx:archive | 18 | 12 | 2 | 3 | 5.0s |
| 2 | /opsx:propose | 27 | 26 | 1 | 8 | 6.3s |
| 2 | /opsx:apply | 33 | 31 | 1 | 8 | 19.1s |
| 2 | /opsx:archive | 21 | 14 | 2 | 2 | 3.9s |
| 8 | /opsx:propose | 26 | 25 | 1 | 10 | 4.9s |
| 8 | /opsx:apply | 51 | 50 | 1 | 11 | 4.4s |
| 8 | /opsx:archive | 14 | 9 | 1 | 2 | 4.3s |

## Table 3: Skill Attribution

| CP | Command | opsx:apply calls | opsx:archive calls | opsx:propose calls | opsx:apply output | opsx:archive output | opsx:propose output |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | /opsx:propose | 0 | 0 | 25 | 0 | 0 | 9416 |
| 1 | /opsx:propose | 0 | 0 | 6 | 0 | 0 | 776 |
| 1 | /opsx:apply | 25 | 0 | 0 | 48200 | 0 | 0 |
| 1 | /opsx:archive | 0 | 18 | 0 | 0 | 3051 | 0 |
| 2 | /opsx:propose | 0 | 0 | 27 | 0 | 0 | 9401 |
| 2 | /opsx:apply | 33 | 0 | 0 | 55429 | 0 | 0 |
| 2 | /opsx:archive | 0 | 21 | 0 | 0 | 3979 | 0 |
| 8 | /opsx:propose | 0 | 0 | 26 | 0 | 0 | 8272 |
| 8 | /opsx:apply | 51 | 0 | 0 | 15570 | 0 | 0 |
| 8 | /opsx:archive | 0 | 14 | 0 | 0 | 3549 | 0 |

## Table 4: Tool Executions

| CP | Command | Tool Results | Bash | Edit | Write | Read | TodoWrite | Agent | Other |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | /opsx:propose | 24 | 12 | 0 | 5 | 1 | 5 | 0 | 1 |
| 1 | /opsx:propose | 6 | 5 | 0 | 0 | 1 | 0 | 0 | 0 |
| 1 | /opsx:apply | 24 | 13 | 2 | 1 | 5 | 3 | 0 | 0 |
| 1 | /opsx:archive | 16 | 9 | 0 | 2 | 2 | 0 | 1 | 2 |
| 2 | /opsx:propose | 28 | 12 | 0 | 5 | 5 | 5 | 0 | 1 |
| 2 | /opsx:apply | 32 | 6 | 10 | 1 | 11 | 4 | 0 | 0 |
| 2 | /opsx:archive | 19 | 5 | 3 | 0 | 8 | 0 | 1 | 2 |
| 8 | /opsx:propose | 25 | 12 | 0 | 4 | 3 | 5 | 0 | 1 |
| 8 | /opsx:apply | 50 | 35 | 7 | 1 | 3 | 3 | 0 | 1 |
| 8 | /opsx:archive | 12 | 7 | 0 | 1 | 1 | 0 | 1 | 2 |

*10 queries across 3 checkpoints*
