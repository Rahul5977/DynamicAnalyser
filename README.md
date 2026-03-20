# DynamicAnalyser
1.1 Problem Statement
Modern software teams deploy code through CI/CD pipelines — automated sequences of steps like installing dependencies, running tests, building artefacts, and deploying to servers. These pipelines often have unexplained slowdowns: a pipeline that ran in 18 seconds last week now takes 25 seconds. Developers waste hours reading raw log files trying to find the cause.
DynamicAnalyser solves this by automatically ingesting GitHub repository source code and CI/CD execution logs, correlating them, and using a large language model (LLM) to diagnose why a particular pipeline step is slow and what code change would fix it.

Primary Objective : Reduce CI/CD pipeline execution time from 20 seconds to 15 seconds (25% improvement) by identifying the root cause of slowness through AI-powered dynamic log analysis and code correlation.

1.3 Key Innovations
Dynamic analysis — analyses logs produced at runtime, not just static source code
Trace correlation — maps each slow log event back to the exact function in the source code
AI root cause engine — uses an LLM with structured context to explain WHY a step is slow
Fix recommendations — outputs ranked, actionable suggestions with estimated time savings
GitHub integration — automatically posts analysis as a PR comment on every slow run


Layer	Name	Purpose	Key Components
Layer	Name	Purpose	Key Components
1 — Sources	Data ingestion sources	Raw inputs to the system	GitHub repo, CI logs, runtime metrics
2 — Ingestion	Parsing & indexing	Normalise and structure raw data	Log parser, AST indexer, trace correlator
3 — AI Core	Intelligence layer	Find problems and suggest fixes	Bottleneck ranker, LLM engine, recommender
4 — Output	Delivery layer	Present findings to the developer	Dashboard UI, report generator, PR commenter

