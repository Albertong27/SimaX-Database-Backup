# Scheduling

Create or edit a policy, choose its trigger and IANA time zone, then select **Preview upcoming runs**. The preview calculates up to five future occurrences within eight years, with local UTC offsets. Sparse schedules may show fewer than five. Preview does not save a policy, enqueue a job, or connect to a database. A paused policy can be previewed but cannot enqueue jobs.

| Trigger | Configuration |
| --- | --- |
| Manual | Run explicitly from the policy page |
| Daily | Local time and IANA time zone |
| Weekly | One or more weekdays, local time and IANA time zone |
| Cron | Five numeric fields and IANA time zone |

## Cron syntax

Fields are `minute hour day-of-month month day-of-week`. Bounds are `0–59`, `0–23`, `1–31`, `1–12`, and `0–7`; Sunday is either `0` or `7`. The weekly form uses Monday through Sunday labels (the API's weekly array uses Monday `0` through Sunday `6`).

Supported syntax: `*`, numeric values, comma-separated lists, ascending inclusive ranges, and positive steps. `*/15` selects every fifteenth value from the field minimum; `8-18/2` selects 8, 10, 12, 14, 16 and 18; `10/20` in the minute field selects 10, 30 and 50. Steps must not exceed the field's size. An expression is limited to 256 characters.

| Expression | Meaning in the policy's time zone |
| --- | --- |
| `0 3 * * *` | Every day at 03:00 |
| `0 */6 * * *` | 00:00, 06:00, 12:00 and 18:00 daily |
| `15 9 * * 1-5` | Weekdays at 09:15 |
| `0 2 1 * *` | First day of each month at 02:00 |
| `0 9 29 2 *` | February 29 at 09:00 in leap years |

When both day fields restrict the possible values, either may match (OR). For example, `0 9 1 * 1` runs at 09:00 on the first of the month and on Mondays. A field that expands to every valid day value is unrestricted. Month, hour and minute must always match. Impossible dates such as February 31 with an unrestricted weekday are rejected.

Names such as `MON`, macros such as `@daily`, seconds/year fields, wraparound ranges, and `L`, `W`, `#`, `H` or `R` extensions are not supported. These are calendar schedules, not elapsed-time intervals: DST can change the elapsed time between occurrences.

## Execution rules

- The runtime and its host must remain running and awake. Closing the browser does not stop schedules. Planned times are not guarantees of immediate execution: one worker serializes all jobs.
- After downtime, at most the latest due occurrence from the current local day is considered for each policy. Earlier occurrences and earlier local days are skipped; there is no backlog replay. A weekly Monday occurrence does not catch up on Tuesday.
- A nonexistent DST wall time is skipped. A repeated wall time is considered only at its first occurrence. Previews and execution share this calculation, including when a clock has just moved backward.
- Creating, editing or re-enabling a policy excludes occurrences before the edit timestamp. An edit that races with scheduling invalidates the scheduler's old policy revision. Already accepted jobs retain their policy snapshots.
- Occurrence claims and enqueue/coalescing are transactional and survive restarts. Daily and weekly schedules use one claim per policy/local day, including legacy daily claims. Editing their time after a run on that day does not authorize a second scheduled run that day. Cron claims use the UTC minute; editing a cron expression cannot replay a previously claimed UTC occurrence.
- If another backup for the source is queued or running, the due occurrence is consumed and coalesced into that active job, with an audit record. It does not reappear after that job finishes or fails. Manual requests during an active backup are rejected.
- Pausing stops future enqueues; cancel an already queued job separately. Failed or cancelled scheduled runs are not automatically retried for the same occurrence; use **Run now** or wait for the next occurrence.

## API and evidence

`POST /api/schedules/preview` accepts `trigger`, `time`, `timezone`, `weekdays` and `cron`, with the same validation as a saved policy. It returns `timezone`, `horizon_years` and `occurrences` containing `utc` and `local` ISO timestamps. The usual local request header is required. Manual schedules return an empty list.

Scheduled runs record `scheduled_for` in UTC alongside the immutable policy revision. The run detail view shows this intended time separately from actual start and finish times. No SQLite schema migration or new runtime dependency is needed for existing catalogs.

Tests cover syntax and calendar validation, weekly mapping, day-field OR semantics, time zones, DST gaps and folds, leap-day bounds, preview without writes, missed occurrences, coalescing, restart deduplication, policy-edit races and existing daily occurrence records. The default suite uses isolated catalogs and synthetic adapters; these checks do not operate on configured user databases.
