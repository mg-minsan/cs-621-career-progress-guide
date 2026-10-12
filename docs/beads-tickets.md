# Beads Tickets

Epic: **career-m5z — SkillsFuture career and course recommendation workflow**

Source plan: [implementation-plan.md](implementation-plan.md)

| ID | Ticket |
|---|---|
| `career-m5z.1` | Verify and ingest the four SkillsFuture workbooks |
| `career-m5z.2` | Implement read-only structured lookup and role comparisons |
| `career-m5z.3` | Export JSON and Markdown profiles for all roles |
| `career-m5z.4` | Create representative retrieval and recommendation evaluation fixtures |
| `career-m5z.5` | Implement role and course keyword search baseline |
| `career-m5z.6` | Define and validate user profile schema |
| `career-m5z.7` | Build and evaluate role/course semantic retrieval |
| `career-m5z.8` | Discover career directions and assess learning priorities |
| `career-m5z.9` | Implement evidence-backed course matching and constraint checks |
| `career-m5z.10` | Expose agent tools and generate cited career guides |
| `career-m5z.11` | Validate hybrid recommendations and document MVP operation |
| `career-m5z.12` | Evaluate optional unique-skill normalisation |

The ingestion ticket is closed as completed; remaining tickets are open with dependency links. Unique-skill normalisation is optional (P3).

```sh
bd ready
bd show career-m5z
bd graph career-m5z
```
