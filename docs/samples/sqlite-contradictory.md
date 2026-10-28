> **Sample report.** Mode: live. Date: 2026-10-28. Model: gpt-6.1-terra (reasoning effort low). Prompt version: 2026-10-28.2. Produced by `predixion eval --mode live` and exported with the app's Markdown renderer; not edited. Source: `evals/results/live-gpt-6.1-terra.json`.

# Is SQLite suitable for production web applications?

**Status:** Partial answer · **Mode:** live · **Model:** gpt-6.1-terra · **Created:** 2026-10-28 11:35 UTC · **Run:** `run_63400c3ed215eeb6319c58bc`

> Stopped: Reached the limit of 2 research rounds.

## Short answer

Yes. SQLite can be suitable as the primary database for a production web application, particularly when the database is local to the application server and writes can take turns. The main uncertainty is whether its single-writer model and deployment constraints will meet your workload and recovery requirements. [E23] [E5] [E12] [E13] [E9]

## Findings

- SQLite supports transactions and ACID properties. Production planning still needs a backup and recovery approach; a third-party replication tool such as Litestream is one option. [E27] [E1] [E9]
- In WAL mode, multiple readers can run concurrently with one writer. Writes are serialized and can queue under sustained load; multiple users writing through one application server does not by itself rule SQLite out. [E12] [E3] [E13] [E5]
- SQLite says web capacity depends on database usage and that fewer than 100,000 hits per day should generally work, but calls that estimate conservative rather than a hard limit. Treat request counts as a rough signal, not a capacity guarantee. [E18] [E19] *(interpretation)*
- Embedding SQLite avoids a database server to manage, but it has no database network authentication layer. Protect database files with appropriate permissions and consider encryption for sensitive data. [E7] [E11] [E26] *(recommendation)*
- Consider PostgreSQL or MySQL when write contention cannot be tolerated, or a database server when separate services need network access to shared data. Multi-server write requirements may also warrant a managed or extended SQLite option; separate databases per tenant are another possible architecture when the application permits it. [E3] [E22] [E30] [E6] [E10] *(recommendation)*
- For very large databases, SQLite says filesystem file-size limits matter and recommends considering a client/server engine. A later PostgreSQL migration also requires attention to schema differences. [E20] [E21] [E15]

## Conflicting evidence

- One source says any application with more than one writer needs PostgreSQL, and another warns of contention even under light multiuser load. Other sources say multiple users can write through one application server and describe writes as serialized rather than prohibited. [E14] [E17] [E5] [E12] [E22]. Resolution: SQLite's own guidance distinguishes writers that can queue from simultaneous writes that cannot. This supports the narrower conclusion that multiple potential writers are not automatically disqualifying, while contention remains workload-dependent.
- Sources disagree on K2 about SQLite. [E1] [E2] [E3] [E5] [E14] [E17]. Unresolved.
- Sources disagree on K4 about SQLite. [E2] [E3] [E4] [E5] [E14] [E17]. Unresolved.

## Coverage

| Criterion | Status | Evidence |
|---|---|---|
| K1: Establish production reliability, transactions, durability, and backup and recovery considerations. | stale | E1, E7, E9, E25, E27 |
| K2: Assess concurrency, write throughput, and scaling constraints, including deployment across servers. | conflicting | E1, E2, E3, E4, E5, E6, E8, E9, E10, E11, E12, E13, E14, E17, E18, E19, E20, E21, E22, E23, E24, E28, E29, E30 |
| K3: Identify operational benefits and limitations, including security, maintenance, and hosting. | stale | E7, E8, E9, E11, E15, E26 |
| K4: Identify suitable and unsuitable workload patterns and practical alternatives or migration triggers. | conflicting | E2, E3, E4, E5, E6, E10, E13, E14, E15, E16, E17, E18, E19, E20, E21, E22, E23, E24, E29, E30 |

## Confidence

**Low.** Low: 0 of 4 required criteria are supported; 7 of 7 checked claims are fully supported; evidence comes from 8 independent sites; 2 unresolved conflicts; 2 required criteria are supported only by old or undated sources.

## Limitations

- Research stopped early: Reached the limit of 2 research rounds.
- K1 (Establish production reliability, transactions, durability, and backup and recovery considerations.): stale. No supporting source is dated within 730 days.
- K2 (Assess concurrency, write throughput, and scaling constraints, including deployment across servers.): conflicting. Sources disagree.
- K3 (Identify operational benefits and limitations, including security, maintenance, and hosting.): stale. No supporting source is dated within 730 days.
- K4 (Identify suitable and unsuitable workload patterns and practical alternatives or migration triggers.): conflicting. Sources disagree.
- Publication dates are provider estimates or dates found in page text and may be inaccurate.
- The reviewed evidence does not establish transaction durability under specific storage and configuration choices or provide a tested backup and restore procedure.
- Throughput figures lack workload and benchmark details, so they cannot establish capacity for a particular application.
- The supporting sources have no publication dates in the provided evidence; freshness cannot be verified.
- The evidence does not establish the security, availability, or operational properties of the named replication and managed-service alternatives.

## Assumptions

- The question concerns SQLite as the primary database for a typical web application, rather than solely as a cache or embedded client-side database.
- Suitability depends on workload and deployment; the research will address common scenarios rather than assume a particular application size.

## Next steps

- Benchmark representative reads, writes and peak contention on the intended hardware and deployment topology.
- Choose and test a backup and restore process against the application's recovery requirements.
- Review file access controls, encryption needs and hosting constraints before deployment.
- Define migration triggers for unacceptable write queues, shared network access or database size, and assess schema changes needed for an alternative.
- Find primary or independent sources for: Establish production reliability, transactions, durability, and backup and recovery considerations..
- Find primary or independent sources for: Identify operational benefits and limitations, including security, maintenance, and hosting..

## Evidence

- **[E1]** SQLite in Production 2026: Real Benchmarks, Limits, and When to Migrate to Postgres - Sesame Disk (sesamedisk.com): “Native replication \| None (requires Litestream/LiteFS) \| Built-in streaming replication”
- **[E2]** SQLite in Production 2026: Real Benchmarks, Limits, and When to Migrate to Postgres - Sesame Disk (sesamedisk.com): “The daily.dev production guide explicitly warns that SQLite "struggles with write-heavy workloads" and recommends Postgres for apps that "need thousands of concurrent write transactions per second."”
- **[E3]** Why SQLite Is a Better Default Database Than You Think \| MindStudio (mindstudio.ai): “Even with WAL mode, if you're processing thousands of writes per second with high contention, Postgres or MySQL will serve you better. WAL mode handles concurrent reads fine but writes are still serialized.”
- **[E4]** Why SQLite Is a Better Default Database Than You Think \| MindStudio (mindstudio.ai): “With WAL mode enabled, SQLite handles thousands of read queries per second and hundreds of writes per second on modern hardware.”
- **[E5]** Why SQLite Is a Better Default Database Than You Think \| MindStudio (mindstudio.ai) (contradicts): “Multiple users can write through a single application server - that's the normal case.”
- **[E6]** Why SQLite Is a Better Default Database Than You Think \| MindStudio (mindstudio.ai): “If you need multi-server writes, that's when you'd look at managed database options like Supabase or Turso (which extends SQLite for multi-region scenarios).”
- **[E7]** Why SQLite Is a Better Default Database Than You Think \| MindStudio (mindstudio.ai): “The operational simplicity of SQLite - no server to manage, trivial backups, automatic migrations - reduces overhead significantly.”
- **[E8]** Scalable SQLite (docs.servicestack.net): “To avoid SQLite concurrency write exceptions all DB Writes should be executed within its database lock or a named worker.”
- **[E9]** Scalable SQLite (docs.servicestack.net): “That's about it, by using any of the above techniques to guard against concurrent writes you can take advantage of the simplicity, value and performance benefits of SQLite in your Apps and utilize a solution like litestream.io for real-time replication of your SQLite databases to highly reliable managed storage.”
- **[E10]** Scalable SQLite (docs.servicestack.net): “In the rare cases where you need to scale beyond a single server you'll initially be able to scale out your different App databases onto different servers. Beyond that, if your App permits you may be able to adopt a multi-tenant architecture like Bluesky Social with each tenant having their own SQLite database to effectively enable infinite scaling.”
- **[E11]** Postgres vs SQLite \| Tinybird (tinybird.co): “SQLite is a C library embedded directly in your application process. There is no server, no network protocol, no authentication layer, and no concurrent write access from multiple processes.”
- **[E12]** Postgres vs SQLite \| Tinybird (tinybird.co): “SQLite in WAL (Write-Ahead Logging) mode supports one concurrent writer plus multiple concurrent readers.”
- **[E13]** Postgres vs SQLite \| Tinybird (tinybird.co): “SQLite's single-writer constraint means concurrent writes queue up, and under high write load, throughput degrades.”
- **[E14]** Postgres vs SQLite \| Tinybird (tinybird.co) (contradicts): “Any application with more than one writer, whether multiple application servers hitting the same database, background workers alongside a web server, or multiple users modifying shared data, needs Postgres.”
- **[E15]** Postgres vs SQLite \| Tinybird (tinybird.co): “The migration from SQLite to Postgres is relatively straightforward because both use SQL, but schema differences (strict types, explicit primary keys with UUID vs ROWID, TIMESTAMPTZ vs TEXT dates) require attention.”
- **[E16]** SQLite on a production server? (serverfault.com): “If you are generally only \_reading\_ data then you get good performance in my experience. So, SQLite can be used as a caching system to store database server reads, particulary remote ones or complex queries.”
- **[E17]** SQLite on a production server? (serverfault.com) (contradicts): “You absolutely do not want to try to use it as some sort of standalone MySQL/PostgreSQL/MS-SQL replacement in a multiuser enviroment because the entire DB is locked on write. You'll be dealing with contention issues on even a light load which will destroy performance.”
- **[E18]** Appropriate Uses For SQLite (sqlite.org): “Generally speaking, any site that gets fewer than 100K hits/day should work fine with SQLite. The 100K hits/day figure is a conservative estimate, not a hard upper bound.”
- **[E19]** Appropriate Uses For SQLite (sqlite.org): “The amount of web traffic that SQLite can handle depends on how heavily the website uses its database.”
- **[E20]** Appropriate Uses For SQLite (sqlite.org): “And even if it could handle larger databases, SQLite stores the entire database in a single disk file and many filesystems limit the maximum size of files to something less than this.”
- **[E21]** Appropriate Uses For SQLite (sqlite.org): “So if you are contemplating databases of this magnitude, you would do well to consider using a client/server database engine that spreads its content across multiple disk files, and perhaps across multiple volumes.”
- **[E22]** Appropriate Uses For SQLite (sqlite.org): “If many threads and/or processes need to write the database at the same instant (and they cannot queue up and take turns) then it is best to select a database engine that supports that capability, which always means a client/server database engine.”
- **[E23]** Appropriate Uses For SQLite (sqlite.org): “If the "application" is an application server and if the content resides on the same physical machine as the application server, then SQLite might still be appropriate even though the end user is another network hop away.”
- **[E24]** How to Set Up SQLite for Production Use (oneuptime.com): “Many high-traffic applications run SQLite in production successfully, including some serving millions of requests per day.”
- **[E25]** How to Set Up SQLite for Production Use (oneuptime.com): “WAL mode enables a simple form of point-in-time recovery. The WAL file contains recent transactions that have not been checkpointed:”
- **[E26]** How to Set Up SQLite for Production Use (oneuptime.com): “Set appropriate file permissions and consider encryption for sensitive data:”
- **[E27]** What Is SQLite, and When Is It Enough Instead of a Full Database Server? \| xTom (xtom.com): “Despite that simplicity, SQLite supports the vast majority of standard SQL: transactions, joins, indexes, triggers, views, and full ACID compliance (atomicity, consistency, isolation, durability).”
- **[E28]** What Is SQLite, and When Is It Enough Instead of a Full Database Server? \| xTom (xtom.com): “Modern SQLite deployments almost always enable WAL (write-ahead logging) mode instead, which writes changes to a separate log file first and lets readers continue accessing the main database file without blocking.”
- **[E29]** What Is SQLite, and When Is It Enough Instead of a Full Database Server? \| xTom (xtom.com): “If multiple processes or many simultaneous users are writing to the database constantly, SQLite's single-writer model will eventually queue those writes and slow things down, even in WAL mode.”
- **[E30]** What Is SQLite, and When Is It Enough Instead of a Full Database Server? \| xTom (xtom.com): “If you need several separate services connecting to the same database over a network, you need a real database server that can manage concurrent client connections properly.”

## Sources

- **S2** How to Set Up SQLite for Production Use · medium · <https://oneuptime.com/blog/post/2026-02-02-sqlite-production-setup/view>
- **S7** Postgres vs SQLite \| Tinybird · medium · <https://www.tinybird.co/blog/postgres-vs-sqlite>
- **S8** Why SQLite Is a Better Default Database Than You Think \| MindStudio · medium · <https://www.mindstudio.ai/blog/why-sqlite-is-a-better-default-database>
- **S10** Scalable SQLite · high · <https://docs.servicestack.net/ormlite/scalable-sqlite>
- **S12** SQLite in Production 2026: Real Benchmarks, Limits, and When to Migrate to Postgres - Sesame Disk · medium · <https://sesamedisk.com/sqlite-in-production-2026-benchmarks-limits>
- **S13** Appropriate Uses For SQLite · medium · <https://www.sqlite.org/whentouse.html>
- **S14** SQLite on a production server? · medium · <https://serverfault.com/questions/114524/sqlite-on-a-production-server>
- **S17** What Is SQLite, and When Is It Enough Instead of a Full Database Server? \| xTom · medium · <https://xtom.com/blog/what-is-sqlite>
- **S1** Everyone Is Wrong About SQLite - DEV Community · low · <https://dev.to/shayy/everyone-is-wrong-about-sqlite-4gjf>
- **S3** Using SQLite in Production · medium · <https://www.k-innovations.net/articles/2023/10/01/using-sqlite-in-production.html>
- **S4** What Is SQLite? The Database That Runs Inside Your App \| MindStudio · medium · <https://www.mindstudio.ai/blog/what-is-sqlite>
- **S5** SQLite in Modern Web Production: Dreams Becoming Reality · medium · <https://medium.com/data-science/sqlite-in-production-dreams-becoming-reality-94557bec095b>
- **S6** SQLite on FreeBSD: Embedded Database Review · medium · <https://freebsdsoftware.org/blog/sqlite-freebsd-review.html>
- **S9** Everyone Is Wrong About SQLite (Here’s When It Beats Postgres) · medium · <https://www.youtube.com/watch?v=t20KyfjtUs4>
- **S11** \> \*If you're querying a multi-GB SQLite database\* In which case SQLite is probab... \| Hacker News · low · <https://news.ycombinator.com/item?id=44565664>
- **S15** SQLite for Production: When and How to Use It Beyond Prototyping \| daily.dev · medium · <https://daily.dev/blog/sqlite-production-guide-when-how-to-use-beyond-prototyping>
- **S16** SQLite as a production database for a low-traffic site · low · <https://stackoverflow.com/questions/913067/sqlite-as-a-production-database-for-a-low-traffic-site>

## Execution

- Rounds: 2; searches: 3; pages read: 8; model calls: 6
- Tokens: 18995 in / 4694 out; estimated cost: $0.0745
- Duration: 66.0 s; prompt version 2026-10-28.2
- Verification: 7/7 claims supported
