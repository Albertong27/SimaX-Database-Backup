# SimaX Database Backup — Product Requirements Document

| Field | Value |
| --- | --- |
| Organization | Simply Smart X |
| Short name | SimaX |
| Product | SimaX Database Backup |
| Document version | 0.1 |
| Date | 2026-10-19, Asia/Jakarta |
| Status | Draft target requirements; implementation progress is tracked separately in development-status.md |
| Intended distribution | Open source on GitHub; license and repository owner pending |
| Accountable owner | Simply Smart X; individual product and engineering owners to be assigned |

## 1. Purpose and evidence boundary

Define the user problem, desired outcomes, functional requirements, acceptance criteria, and unresolved decisions for managing backups and restores across multiple database systems.

The founder's requested capabilities are the source of product requirements. There are no customer interviews, incident datasets, performance benchmarks, or validated business-impact measurements yet. User pains below are discovery hypotheses. Numerical examples illustrate exposure; they are not market statistics, measured customer outcomes, or product guarantees. Success targets are proposed and require validation.

The problem statement deliberately avoids proposed solutions. Later sections translate the requested capabilities into observable behavior. They do not select an application architecture, UI framework, database access library, change-capture mechanism, or encryption algorithm.

## 2. Problem statement

People responsible for databases across MySQL, PostgreSQL, Oracle Database, and Microsoft SQL Server struggle to determine whether their important data and database behavior can actually be recovered when needed. They must account for different object types, permissions, backup semantics, storage destinations, and restore constraints across environments. As the number of databases grows, checking coverage and maintaining recovery procedures consumes more time and becomes harder to keep accurate.

The pain is most acute when data changes between recovery points, a backup silently excludes a required object, or a seemingly successful backup cannot be restored to the available server. Operators may discover missing dependencies, unusable files, inaccessible destinations, or unavailable encryption credentials only during an incident. Recovery then depends on manual investigation and individual expertise while users wait for service to return.

The consequences include exposure to lost changes, longer service interruptions, repeated administrative work, and uncertainty about which recovery point is trustworthy. Teams also struggle to recover a limited set of objects without disrupting unrelated data. They cannot reliably assess their recovery readiness from file existence or a successful export alone.

### 2.1 Specific pain and consequences

| User pain | Situation in which it appears | User or business consequence | Evidence to collect |
| --- | --- | --- | --- |
| Fragmented operational knowledge | Different engines and environments require different procedures | Repeated work, inconsistent coverage, dependence on a few operators | Time spent per database; number of tools and handoffs |
| Unclear coverage of database behavior | Tables exist in a backup but dependent indexes, routines, triggers, permissions, or other objects are absent | Restored data may not support the original application behavior | Missing-object incidents and restore comparison results |
| Recovery points lag meaningful changes | Important changes occur between backups or an expected trigger is missed | Recent work may have to be reconstructed or may be unrecoverable | Age of latest usable recovery point; change volume during that interval |
| Backup completion is mistaken for recoverability | File creation succeeds but integrity, dependencies, or restore compatibility are untested | Failures surface during an outage | Percentage of artifacts with recent successful restore evidence |
| Storage and access vary across environments | A destination is full, unreachable, misconfigured, or credentials have expired | Required recovery copies are missing or inaccessible | Transfer failures, time to detection, storage growth |
| Restore decisions are difficult under pressure | Source server is unavailable or the target already contains important data | Longer interruption or accidental overwrite of unrelated data | Recovery time, operator actions, overwrite incidents |
| Recovery depends on the original installation | Catalog, configuration, tooling, or keys are lost with the host | Existing backup files may become difficult or impossible to use | Fresh-install recovery drill results |

### 2.2 Quantifying impact without inventing evidence

| Dimension | Illustrative calculation | Interpretation and limits |
| --- | --- | --- |
| Administrative effort | 20 databases × 15 minutes of manual checking per database per week = 300 minutes, or 5 hours/week | Assumes this amount of checking is currently necessary; measure it in interviews and observation |
| Potential recovery gap | Recovery points exactly 24 hours apart imply a worst-case gap approaching 24 hours and an average gap of 12 hours if incident times are uniformly distributed | Assumes successful, usable snapshots and negligible backup delay; failed or delayed backups increase exposure |
| Changes exposed to loss | At 25 committed changes/minute, a 12-hour recovery gap contains 18,000 changes | Changes are not necessarily distinct rows, transactions, or confirmed losses; other recovery mechanisms may reduce loss |
| Interruption impact | 40 affected staff × 2 hours unable to work = 80 staff-hours disrupted | Illustrative only; actual effects depend on incident severity, alternate workflows, and service usage |

Track actual recovery-point age from the data snapshot represented by a usable artifact, not just its upload completion time. Record recovery duration from the agreed incident or recovery-start timestamp through application validation. Capture both technical restore time and time spent locating, accessing, and validating the backup.

## 3. Users and jobs to be done

| User | Responsibility | Job to be done | Evidence of success |
| --- | --- | --- | --- |
| Database administrator | Data integrity and recovery | Know what is protected and restore a complete or selected scope | Required data and database behavior work after restore |
| DevOps or platform engineer | Operations across environments | Maintain dependable backup execution and diagnose failures | Expected runs are accounted for and failures are actionable |
| Developer or small-team administrator | Development, staging, and smaller production systems | Preserve changes and recover without deep knowledge of every engine | Completes a tested backup and restore without undocumented commands |
| IT operator or managed-service operator | Several servers or customer environments | Keep sources, destinations, and restore targets clearly separated | No accidental cross-environment action or credential use |
| Reviewer or auditor | Operational evidence | Determine who changed protection policies and whether recovery was tested | Traceable configuration changes, run history, and restore results |

Managed-service use is a persona to validate, not a commitment to multi-tenant hosting in the first release.

## 4. Desired outcomes and proposed success measures

RPO (recovery point objective) is the maximum acceptable age of recoverable data. RTO (recovery time objective) is the acceptable duration to restore service. Both are workload-specific; this product must report evidence rather than promise one universal RPO or RTO.

| ID | Desired outcome | Proposed measurable target | Validation method |
| --- | --- | --- | --- |
| OUT-01 | Less routine administrative effort | At least 50% reduction from each pilot team's measured weekly baseline | Compare two baseline weeks with four pilot weeks for equivalent protected scope |
| OUT-02 | Faster initial setup | At least 4 of 5 pilot operators complete a first backup within 15 minutes, with credentials and prerequisites ready | Timed usability sessions; record excluded provisioning time |
| OUT-03 | Demonstrable recovery | Every capability advertised as supported passes its required round-trip fixture tests | Per-engine/version/object/format/destination release matrix |
| OUT-04 | Clear protection status | 100% of accepted jobs reach a visible terminal or explicitly interrupted state; no silent missing runs in fault tests | Restart, queue, disconnect, and storage-failure tests |
| OUT-05 | Timely trigger processing | p95 eligible-event-to-job-queued latency ≤ 60 seconds in an agreed reference environment | Record receipt, eligibility after debounce, and queued timestamps separately; report sample size and load |
| OUT-06 | Actionable failures | Every tested failure identifies stage, affected source/destination, safe next action, and correlation ID | Fault-injection acceptance review; exclude credentials and row contents |
| OUT-07 | Recovery readiness is visible | Every artifact shows integrity status and whether, when, and where a restore was tested | Catalog and restore-history inspection |

Reference hardware, database sizes, concurrency, event load, network conditions, and throughput targets must be agreed before performance acceptance. These targets are draft gates, not measured results. Production reliability and RPO attainment will be measured during pilots before numerical service commitments are made.

## 5. Scope and delivery boundaries

### 5.1 Required product scope

- Management through a web application or a desktop application; Rust is the preferred implementation language if desktop is selected.
- Multiple independently managed sources spanning MySQL, PostgreSQL, Oracle Database, and Microsoft SQL Server.
- Manual execution plus schedule, database-change, table-change, webhook, MQTT, and Redis triggers.
- Selection of tables, indexes, triggers, functions, procedures, and other supported engine-specific objects.
- Local filesystem, FTP, SFTP, AWS S3, and Google Cloud Storage destinations.
- A single SQL file, multiple SQL files grouped by table or schema, and an encrypted SimaX-specific binary format.
- Restoration to the original server or a different compatible server.

All four engines, all requested trigger classes, all named destinations, and all three output modes remain required in the intended product scope. A proposed pilot subset below sequences delivery; it does not remove requirements.

### 5.2 Explicit boundaries

- “Different server” initially means a compatible target running the same database engine. Cross-engine conversion, such as MySQL to PostgreSQL, requires a separate product decision and is outside the initial scope.
- Change-triggered execution means a change makes a backup eligible to run. It does not imply incremental backup, transaction-log archiving, point-in-time recovery, or continuous replication.
- A source database trigger object is an object to preserve; an application backup trigger is an event that starts work. These meanings must be distinct in product terminology.
- A consistent backup within one database does not imply an atomic recovery point across several databases or servers.
- Physical engine-native backups, cluster-wide disaster recovery, automatic failover, log-chain recovery, and zero-downtime guarantees are not assumed.
- General-purpose data migration, arbitrary query-result export, managed hosting, billing, and regulatory certification are outside the initial scope.
- Native dump formats and the SimaX binary format must not be presented as interchangeable SQL files.

### 5.3 Proposed delivery sequence

| Phase | Scope | Exit gate |
| --- | --- | --- |
| Definition | PRD, research, engine capability investigation, interface decision, license decision | Owners review open decisions and approve a testable scope |
| Pilot | Proposed first engines: PostgreSQL and MySQL; one selected interface; manual/scheduled backups; local storage; single SQL output; complete and selected table scopes with dependencies; same-engine alternate-server restore | Supported pilot combinations pass backup/restore tests and usability review |
| Product scope completion | Oracle and SQL Server; remaining objects; change, webhook, MQTT, Redis triggers; FTP/SFTP/S3/GCS; split SQL and encrypted binary | Every original requirement is delivered with a declared support matrix or its scope change explicitly approved |
| Release readiness | Hardening, documented compatibility, recovery drills, operational evidence, public contribution and release processes | Required acceptance scenarios pass; no unresolved critical data-loss, integrity, or credential-exposure defects |

The pilot sequence is a recommendation for planning, not an approved commitment or estimate. No release dates are assigned without engineering discovery.

## 6. Functional requirements

“Must” identifies required product behavior. Engine-dependent requirements must be evaluated against an explicit capability matrix. Unsupported combinations must be visible and blocked before execution; they must never silently fall back to a different scope or format. An unsupported required combination remains an unresolved scope item, not a completed requirement.

### 6.1 Connections and management

| ID | Requirement | Acceptance criterion |
| --- | --- | --- |
| FR-01 | Manage multiple named source and restore-target connections | Add, edit, test, disable, and remove connections; production and non-production identities are clearly distinguishable |
| FR-02 | Inspect engine, version, required tooling, connectivity, permissions, and security prerequisites | Preflight identifies missing privileges and unsupported versions without altering application data |
| FR-03 | Maintain named backup policies with source, object scope, triggers, destination requirements, format, and retention | Saving validates all required fields; each run records an immutable snapshot of the effective policy revision |
| FR-04 | Offer the selected management interface for the full backup and restore lifecycle | Users can configure, run, inspect, cancel, and diagnose jobs through the interface; accessibility criteria in section 10 apply |
| FR-05 | Separate backup execution from the visibility of the management interface | Closing a browser tab or desktop window must not silently cancel accepted jobs or scheduled protection; stopping the actual execution runtime visibly affects protection status |

### 6.2 Backup triggers

All triggers must be attributable to a policy revision, an origin, and an event or schedule occurrence. Eligibility, debounce, queue delay, and execution time must be distinguishable.

| ID | Requirement | Acceptance criterion |
| --- | --- | --- |
| FR-10 | Manual runs with explicit policy and scope | A request returns a run identifier; disabled or invalid policies cannot run silently |
| FR-11 | Schedule-based execution with an explicit time zone | Show upcoming occurrences; define daylight-saving skipped/repeated times and missed runs after downtime; no unbounded catch-up burst |
| FR-12 | Database-level and table-level change triggers | State which data and/or schema changes are observable per engine and configuration; matching supported changes enqueue eligible jobs; out-of-scope changes do not |
| FR-13 | Make observation gaps and prerequisites visible | Missing permissions, unavailable change history, disconnection, or lost observation continuity mark protection degraded; no claim of uninterrupted change coverage |
| FR-14 | Authenticated webhook trigger | Validate authentication, payload schema, event identity, and authorized policy; reject expired/replayed or malformed requests; acceptance does not imply completion |
| FR-15 | MQTT-based trigger | Configure broker access and topic selection; define QoS, retained-message, reconnect, duplicate, and session-expiry behavior; unrelated topics cannot run a policy |
| FR-16 | Redis-based trigger | Declare supported Redis mechanism, access permissions, acknowledgment, replay, and reconnect behavior; disclose message-loss limits when the chosen mechanism is not durable |
| FR-17 | Coalesce bursts and bound concurrency | Configure debounce and maximum deferral, minimum run interval, and per-source concurrency; record coalesced/skipped/queued events and reasons |
| FR-18 | Prevent duplicate execution and event feedback loops | Repeated event identity within a documented retention window produces at most one eligible run; restored changes and queued reruns follow an explicit policy |

The change-observation approach, Redis mechanism, and exact delivery guarantees are open engineering decisions. Trigger requests must identify preconfigured policies and must not supply arbitrary SQL, executable commands, filesystem paths, or destination credentials. Acknowledged durable requests must survive runtime restart; mechanisms without durable delivery must disclose that limitation and expose observation gaps.

### 6.3 Object scope, dependencies, and consistency

| ID | Requirement | Acceptance criterion |
| --- | --- | --- |
| FR-20 | Discover objects and support whole-database, schema, and explicit-object selection where applicable | Display names, types, and eligibility; distinguish unsupported objects from inaccessible or excluded objects |
| FR-21 | Support schema-only, data-only, and schema-plus-data scopes where compatible | Preview precisely what each mode preserves, including identity/sequence state and other relevant metadata |
| FR-22 | Preserve or explicitly account for dependencies | Selection preview shows dependency additions and external prerequisites; missing required dependencies block execution or require an explicit documented partial-backup acknowledgment |
| FR-23 | Define selection behavior when objects change | Users can distinguish a fixed selection from a rule that includes future matching objects; each run records the resolved object inventory |
| FR-24 | Report consistency guarantees and source impact | State snapshot/locking guarantees, nontransactional limitations, and any required quiescence before execution; multi-file output must not silently combine inconsistent snapshots |
| FR-25 | Detect incomplete exports | Permission errors, unsupported definitions, changed/dropped objects, and partial process failures cannot produce an unqualified successful result |

The following is an inventory for discovery, not a promise that every object can be independently exported or restored in every format:

| Engine | Candidate object scope to evaluate | Important boundary to validate |
| --- | --- | --- |
| MySQL | Databases, tables, views, indexes, constraints, triggers, functions, procedures, scheduled events | Transactional consistency, stored-program privileges, character sets/collations, definers, and account/grant treatment |
| PostgreSQL | Schemas, tables, views/materialized views, indexes, constraints, triggers, functions/procedures, sequences, types, extensions, large objects | Dependency closure, extension prerequisites, ownership, and cluster-global objects versus database-local scope |
| Oracle Database | Schemas, tables/partitions, indexes, constraints, triggers, functions, procedures, packages, sequences, views/materialized views, types, synonyms | Mode-specific filters, privileges, server-side prerequisites, supported export representation, and edition/version restrictions |
| Microsoft SQL Server | Databases, schemas, tables, views, indexes, constraints, triggers, functions, procedures, sequences, user-defined types | Logical scripting versus native backup semantics, identities, users/logins, permissions, and server-level dependencies |

Before supporting an object category, publish whether it can be selected independently, included only with a parent, restored selectively, or requires an external prerequisite. Discovery must cover vendor-specific definitions, binary/large values, generated values, non-ASCII identifiers, and large-object storage.

### 6.4 Backup destinations and lifecycle

| ID | Requirement | Acceptance criterion |
| --- | --- | --- |
| FR-30 | Local filesystem destination | Validate access and available capacity; canonicalize paths and prevent unintended traversal or overwrite; report staging and final locations |
| FR-31 | FTP and SFTP destinations | Treat them as distinct protocols; verify SFTP host identity; disclose unencrypted FTP transport and require explicit opt-in; FTPS is an open scope decision |
| FR-32 | AWS S3 destination | Validate bucket, region, prefix, credentials, permissions, and upload/finalization behavior; do not imply support for every S3-compatible service |
| FR-33 | Google Cloud Storage destination | Validate bucket, prefix, credentials, permissions, and upload/finalization behavior |
| FR-34 | Optional multiple copies with explicit completion policy | Mark destinations required or optional; a backup is complete only after every required copy is durably finalized and integrity-checked; optional-copy failure remains visible |
| FR-35 | Safe interruption, retry, and cancellation | Incomplete output is excluded from restorable inventory; retries are bounded and do not overwrite good artifacts; disclose when a transfer must restart |
| FR-36 | Configurable retention and cleanup | Preview expirations, protect pinned/in-use backups and required dependencies, enforce a configured minimum usable-copy count, and audit deletions per destination |
| FR-37 | Preserve evidence of copies and their availability | Record size, checksum, destination, creation/snapshot times, and current known accessibility; stale verification is visible |

Retention must account for destination-side lifecycle rules and externally deleted objects. Object-store listing alone is not proof of successful finalization or integrity. Storage estimates must label assumptions about data size, compression, backup frequency, copies, and retention.

### 6.5 Output formats

| ID | Requirement | Acceptance criterion |
| --- | --- | --- |
| FR-40 | Single SQL file | Produce one executable engine-specific SQL payload for the selected supported scope; document restore prerequisites, ordering, and external dependencies |
| FR-41 | Multiple SQL files | Support grouping by table or schema where those concepts apply; include ordering and dependency metadata, collision-safe filenames, and shared-object treatment |
| FR-42 | Encrypted SimaX-specific binary | Provide a versioned, authenticated encrypted container with documented recovery requirements; wrong keys, tampering, unsupported versions, or truncation must fail safely |
| FR-43 | A recoverable manifest for every output mode | Record engine/version, tool versions, selected/resolved objects, exclusions, consistency, format version, timestamps, file inventory, sizes, integrity evidence, and required prerequisites |
| FR-44 | Format choice reflects actual capability | Validate each engine/object/output combination; never label a native binary dump or data-only export as a complete SQL backup |
| FR-45 | Recovery remains possible after installation loss | Re-import backup artifacts on a fresh installation using documented external credentials/keys; local catalog loss alone must not prevent recovery |

For the single SQL option, “one file” means one SQL payload, not a collection of SQL parts. Whether its manifest is embedded in comments or stored alongside it remains open; the chosen contract must document all files needed for recovery. Multiple SQL output must identify shared definitions and restore order rather than duplicate them unpredictably.

“Proprietary binary” is provisionally interpreted as a SimaX-specific format in an open-source project, not an undisclosed algorithm or paid-only recovery dependency. Publish its format/version policy and recovery tooling. Confirm this interpretation before implementation. Use reviewed cryptographic libraries, never custom cryptography. Key/passphrase recovery, rotation, and migration must be specified; losing the only valid decryption secret may make a backup unrecoverable.

Native Oracle and SQL Server backup/export mechanisms do not by themselves establish support for the requested SQL output modes or independently selectable objects. Feasibility work must prove the actual round trip for each requested combination before committing to implementation coverage.

### 6.6 Restore

| ID | Requirement | Acceptance criterion |
| --- | --- | --- |
| FR-50 | Restore to the original or another compatible server | Identify engine, target version, capabilities, privileges, storage, and connectivity before modifying the target |
| FR-51 | Whole-scope and selective restore where the artifact permits | Preview selected objects, dependency closure, prerequisites, name mappings, and unsupported partial combinations |
| FR-52 | Explicit conflict and overwrite behavior | Default to a non-destructive target choice; show existing objects affected; destructive replacement requires explicit authorization tied to the named target and scope |
| FR-53 | Preflight artifact and target compatibility | Check completeness, integrity, decryptability, version compatibility, encoding/collation, extensions, permissions, owners/definers, and required keys or certificates |
| FR-54 | Execute with visible stages and recovery guidance | Track download, verification, decryption, preparation, replay, and validation; cancellation/failure reports partial effects and safe next steps |
| FR-55 | Validate the restored result | Compare expected object inventory and appropriate data/behavior checks; report exclusions and limitations; a successful import command alone is insufficient |
| FR-56 | Isolated recovery drills | Restore into a disposable compatible target without altering the source; retain evidence identifying artifact, target, checks, time, and outcome |
| FR-57 | Handle potentially active database code | Make routines/triggers and external side effects visible before restore; use isolated drills and explicit target authorization; encrypted files are not inherently trusted |

Preflight cannot guarantee success against a changing target. Revalidate target identity and destructive effects immediately before execution. Restore is not guaranteed atomic across all engines or objects; do not promise automatic rollback. A failed restore must not be automatically retried destructively without a safe documented strategy and authorization.

### 6.7 Status, history, and administration

| ID | Requirement | Acceptance criterion |
| --- | --- | --- |
| FR-60 | Operational history with stable run IDs | Filter by source, policy, trigger, destination, status, and date; distinguish queued, running, cancelling, succeeded, failed, cancelled, and interrupted work |
| FR-61 | Separate backup, integrity, and restore-test states | Display exported/transferred/finalized state, integrity verification evidence, and restore validation evidence separately |
| FR-62 | Actionable alerts for protection degradation | Notify through an approved channel when required copies fail, schedules are overdue, observation gaps occur, or freshness exceeds a configured objective; channels remain to be selected |
| FR-63 | Audit meaningful actions | Record actor, time, scope, policy revision, outcome, and correlation ID for connection/policy changes, manual runs, restores, key changes, and deletions |
| FR-64 | Recovery of application configuration | Export/import non-secret configuration and catalog metadata with version validation; require secure rebinding of secrets when necessary |
| FR-65 | Controlled access | For shared access, distinguish administrator, operator, and read-only capabilities; authorization must be enforced at execution, including webhook and broker requests |

Log retention and access must be configurable. Logs and audit exports must exclude secrets, connection strings containing passwords, decrypted backup contents, and raw production rows.

## 7. Application design considerations — desired experience only

The interface form is undecided. A web application or desktop application satisfies the founder's direction; Rust is preferred if desktop is chosen. No screen layout, framework, process architecture, or component design is proposed here.

The design problem is to let operators answer these questions with minimal ambiguity:

- Which databases are protected, and how old is the latest usable recovery point?
- What exactly will this policy capture, including dependencies and exclusions?
- Why did this run start, and what happens if another event arrives?
- Where are the required copies, and which checks have actually succeeded?
- Can this artifact be restored to the selected target, and what will change there?
- What action is needed after a failure, and what data might already have been changed?

Before choosing the interface, validate single-user versus shared operation, unattended execution, remote administration, supported operating systems, accessibility, installation constraints, and operator familiarity. Product terminology must distinguish a server, database, schema, object, backup policy, run, artifact, copy, and recovery point.

## 8. Critical user journeys

1. **Establish protection:** Identify a source; check prerequisites; select scope; review dependencies and consistency; choose triggers, output, destinations, and retention; validate the effective policy; run a first backup; inspect evidence.
2. **Respond to a failure:** Find the affected policy and stage; determine the last usable recovery point; inspect a redacted cause; correct the issue; rerun safely; confirm required-copy and integrity status.
3. **Recover selected objects:** Identify an artifact and trusted target; review object dependencies and conflicts; authorize affected scope; execute; validate data and behavior; retain recovery evidence.
4. **Recover after host loss:** Install supported recovery tooling elsewhere; obtain artifact and external secrets; reconstruct inventory; preflight a compatible server; restore and validate without depending on the lost local catalog.

These describe required outcomes and decision points, not prescribed screens.

## 9. Reliability and execution semantics

- Accepted durable jobs must remain identifiable after restart. Interrupted jobs must not be reported as successful; operators must see whether retry is safe.
- A source must have bounded concurrency and resource limits. Policies define overlap handling, maximum execution duration, and cancellation behavior.
- Completion must be tied to the declared required destinations and a complete artifact inventory. Partial files or partial object scopes must never masquerade as complete backups.
- A backup can be complete and integrity-checked without having been restore-tested. “Restore validated” requires a recorded successful recovery check, not just a checksum match.
- Backpressure, rate limits, retry exhaustion, missed schedules, lost subscriptions, expired credentials, and exhausted storage must be visible.
- Multiple databases may have different recovery-point timestamps. No cross-database atomicity is implied.
- Source access should be read-only where the supported engine operation allows it. Any setup that changes source configuration or installs objects needs disclosed privileges, operational impact, and explicit administrator consent.

## 10. Non-functional requirements

| ID | Area | Requirement and acceptance evidence |
| --- | --- | --- |
| NFR-01 | Secret handling | Protect stored credentials and encryption material using the chosen platform's approved mechanism; no secrets in Git, process arguments visible to other users where avoidable, logs, or exported configuration; test redaction and access boundaries |
| NFR-02 | Transport and identity | Verify server identities and TLS where supported; SFTP host-key changes fail closed; insecure FTP is explicitly labeled and opted into; credential scope follows least privilege |
| NFR-03 | Encryption and integrity | Use reviewed authenticated encryption with documented key derivation, nonce management, format versioning, and recovery tests; corrupted or unauthenticated encrypted content must not be replayed into a target |
| NFR-04 | Resource usage | Process large artifacts without requiring the entire backup in memory; bound concurrency, temporary storage, and bandwidth; publish measured source overhead on agreed reference workloads |
| NFR-05 | Compatibility | Publish supported server/client versions, editions, operating systems, objects, formats, and restore directions; unsupported downgrade or cross-version paths fail preflight where detectable |
| NFR-06 | Accessibility | Target WCAG 2.2 AA for a web interface; equivalent keyboard operation, focus, accessible names, contrast, and screen-reader checks for desktop; validate critical journeys |
| NFR-07 | Privacy | No production data or credentials in telemetry; operational telemetry, if introduced, requires an explicit policy and user control |
| NFR-08 | Time and localization | Preserve precise event timestamps and offsets; use explicit policy time zones and daylight-saving behavior; support Unicode object names and locale-independent metadata |
| NFR-09 | Recovery portability | Restore tested artifacts using a clean supported installation and separately held recovery secrets; document binary-format compatibility and upgrade policy |
| NFR-10 | Maintainability | Each supported capability has reproducible fixtures, documented limitations, observable errors, and a CI or controlled integration-test path |
| NFR-11 | Upgrade safety | Version configuration/catalog/format changes; failed upgrades must preserve access to existing artifacts and explain recovery or rollback limitations |

No universal database-size ceiling, throughput number, memory budget, availability SLA, or recovery-time guarantee is approved yet. Set these using representative workloads before implementation performance gates are finalized.

## 11. Acceptance and release verification

Use synthetic datasets and disposable targets. Maintain traceability from each requirement ID to tests and documentation. An adapter's successful connection test alone does not establish backup or restore support.

| Scenario | Required evidence | Requirements |
| --- | --- | --- |
| Complete round trip on every declared engine/version | Expected objects, row contents, relevant metadata, and representative application behavior survive backup and restore | FR-20–25, FR-40–45, FR-50–56 |
| Selective object round trip | Dependencies are included or explained; unrelated objects remain unaffected; excluded objects are reported | FR-21–23, FR-51–55 |
| Data types and identities | Unicode, quoted identifiers, nulls, large values, binary data, time values, precision, generated columns, sequences, and identities behave as documented | FR-20–25, FR-55 |
| Schedule edge cases | Time-zone transitions, runtime downtime, missed occurrences, and overlapping runs follow the declared policy | FR-11, FR-17, FR-60 |
| Change-trigger observation | Supported data/schema changes produce the expected eligible runs; high-frequency events are bounded; disconnects surface gaps | FR-12–13, FR-17–18 |
| Webhook and broker delivery | Invalid authentication, duplicate events, replay, reconnects, retained MQTT messages, and chosen Redis delivery semantics behave as documented | FR-14–18 |
| Every destination | Upload, finalization, retrieval, integrity, credential expiry, insufficient capacity, and interrupted transfer are tested | FR-30–37 |
| Every output mode | Single SQL, grouped SQL, and encrypted binary can be recovered according to their declared scope and version contract | FR-40–45 |
| Restore to a different compatible server | Preflight and owner/name mapping work; incompatible versions and missing prerequisites are explained | FR-50–55 |
| Destructive restore or partial failure | Scope authorization is required; no unintended object changes; partial effects and safe next steps are recorded | FR-52–54, FR-57 |
| Corruption and lost credentials | Truncated/tampered artifacts and wrong keys fail safely; missing secrets do not produce false recoverability claims | FR-42–45, FR-53, NFR-01–03 |
| Runtime interruption and host loss | No orphaned success states; artifact inventory can be recovered on a fresh installation | FR-35, FR-45, FR-60–64 |
| Retention and recovery dependencies | Pinned/in-use/minimum copies remain protected; external expiration and deletion are detected | FR-36–37 |
| Permissions and audit | Unauthorized changes and restores are denied; authorized actions are traceable without revealing secrets | FR-63–65, NFR-01–02 |

A release must publish tested combinations and known limitations. Required combinations that remain infeasible need an explicit scope decision; hiding them behind a capability flag does not satisfy the original requirement. Performance results must include hardware, dataset, concurrency, network conditions, repetitions, and percentile measurements.

## 12. Open-source development and CI requirements

- Work under the Simply Smart X / SimaX identity with clear product naming and contributor attribution.
- Maintain a reviewed `main` branch and short-lived topic branches with pull requests and focused commits.
- Require documentation checks initially; add format, lint, build, unit, integration, restore, security, and packaging checks as relevant code is introduced.
- Pin third-party CI actions to immutable revisions, minimize workflow permissions, and keep secrets unavailable to untrusted pull requests.
- Publish a reproducible local development and test procedure with synthetic fixtures.
- Select a license, contributor policy, vulnerability-reporting process, release versioning scheme, and package-signing policy before public distribution.
- Keep the binary format's specification and recovery tooling consistent with the selected open-source license and portability commitments.

Local repository setup and pending hosted settings are tracked in [GitHub setup](github-setup.md). Current implementation and verification boundaries are tracked in [development status](development-status.md); planned requirements must not be presented as delivered capabilities.

## 13. Risks and required validation

| Risk | Why it matters | Validation or decision needed |
| --- | --- | --- |
| Assuming identical engine capabilities | Object selection, consistency, SQL representation, and restore semantics differ | Build and test a per-engine capability matrix before broad support claims |
| Incomplete dependency capture | Selected data can restore successfully while application behavior is broken | Dependency fixtures, explicit prerequisites, and behavior checks |
| Event storms or observation gaps | Backups may overload sources or miss the changes users care about | Burst, disconnect, restart, and replay tests with bounded execution |
| Format or key lock-in | Backups can outlive an installation, maintainer, or product version | Published format/version policy and fresh-install recovery drills |
| SQL output feasibility | Native export utilities may not satisfy the requested logical SQL/object contract | Engine-specific proof of backup and replay before estimating delivery |
| False confidence from green status | A valid file may still fail at recovery time | Distinct integrity and restore-test states, with aging evidence |
| Runtime uptime is misunderstood | A closed or sleeping host cannot execute unattended protection | Explicit operating model and visible protection gaps |
| Restore has side effects or partial results | Restored routines can execute logic; not all operations roll back together | Scoped authorization, isolated drills, clear partial-failure reporting |
| Test infrastructure restrictions | Some database versions/editions require special runtime or licensing arrangements | Confirm distributable fixtures and permitted test infrastructure |
| Public repository lacks license or governance | Intended open-source status does not itself grant reuse rights | Owner selects license and contribution/reporting policies before publication |

## 14. Open decisions and discovery questions

| ID | Decision or question | Proposed owner | Needed before |
| --- | --- | --- | --- |
| DEC-01 | Web or desktop? Single operator or shared administration? Which host operating systems? | Product owner and engineering | Application architecture |
| DEC-02 | Which engine versions, editions, managed services, and restore version directions are required? | Engineering with pilot operators | Adapter scope estimates |
| DEC-03 | Does “different server” require cross-engine migration in a later phase? | Product owner | Public compatibility promises |
| DEC-04 | Which data and schema changes qualify; what source privileges and operational overhead are acceptable? | Database lead and operators | Change-trigger design |
| DEC-05 | Which Redis mechanism and MQTT delivery/session guarantees are needed? | Engineering and integration users | Broker-trigger implementation |
| DEC-06 | Is the SimaX-specific documented binary interpretation acceptable? What key custody and recovery experience is required? | Product owner and security lead | Binary-format design |
| DEC-07 | What are the required consistency guarantees, RPO/RTO objectives, data sizes, source overhead budgets, and concurrency levels? | Pilot operators and engineering | Performance acceptance |
| DEC-08 | Which advanced objects, account/grant metadata, cross-schema dependencies, and server-level prerequisites belong in the supported scope? | Database lead | Object-selection commitments |
| DEC-09 | Are FTPS, S3-compatible providers, cloud key management, immutable storage, or legal holds required? | Product owner | Storage roadmap |
| DEC-10 | Is staged pilot delivery acceptable, and what requirement combinations are essential for the first usable release? | Product owner | Delivery plan approval |
| DEC-11 | Which alert channels, roles, authentication methods, and audit retention are required? | Operators and product owner | Administration design |
| DEC-12 | Which open-source license, GitHub organization, maintainers, and security-reporting channel will be used? | Simply Smart X owner | Public publication |
| DEC-13 | Where should single-file SQL metadata live, and which files must users preserve for independent recovery? | Engineering and product owner | Format contract |

Discovery should include interviews with at least five operators across small teams and larger mixed-engine environments, observation of one existing backup configuration and one restore attempt per available environment, and collection of baseline maintenance effort and recovery metrics. This is a proposed research plan, not completed research.

## 15. Technical references and interpretation

These official references inform feasibility questions only. They do not establish that SimaX has implemented or supports any capability. Reviewed on 2026-10-19; pin the eventual support matrix to specific tested versions.

- [PostgreSQL pg_dump documentation](https://www.postgresql.org/docs/18/app-pgdump.html): database export formats, selective export limitations, consistency, and the distinction between database-local and cluster-global objects.
- [MySQL 8.4 mysqldump documentation](https://dev.mysql.com/doc/refman/8.4/en/mysqldump.html): logical export options, privileges, stored-program scope, and transaction-related constraints.
- [Oracle Database 19c Data Pump Export documentation](https://docs.oracle.com/en/database/oracle/oracle-database/19/sutil/oracle-data-pump-export-utility.html): export modes, filtering, object scope, and dump-file behavior.
- [Microsoft SQL Server backup and restore documentation](https://learn.microsoft.com/en-us/sql/relational-databases/backup-restore/back-up-and-restore-of-sql-server-databases?view=sql-server-ver17): native backup and recovery concepts that must be distinguished from logical SQL export and object-level recovery.

Inference for this PRD: a common management experience must expose capability differences instead of assuming identical object, format, or restore semantics across engines. The exact supported combinations remain to be demonstrated.
