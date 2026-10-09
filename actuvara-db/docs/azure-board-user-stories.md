# Actuvara DB MCP Server (Azure Cosmos DB for MongoDB vCore)

**Epic:** A read-only MCP server that lets AI assistants (GitHub Copilot and Claude Code) understand and query the Actuvara database (intellidoc, 60 collections): collections, fields, relationships and data - without being able to insert, update or delete anything.

| # | User story | State |
|---|---|---|
| 1 | Connect the MCP server to Azure Cosmos DB for MongoDB (vCore) | Closed |
| 2 | Discover collections and their configuration | Closed |
| 3 | Infer the fields of each collection | Closed |
| 4 | Infer and verify relationships between collections | Closed |
| 5 | Get an overview of the whole database in one call | Closed |
| 6 | Read data from collections with my own queries | Closed |
| 7 | Enforce read-only access (select only - no insert, update or delete) | Closed |
| 8 | Use the MCP server from GitHub Copilot in VS Code | Closed |
| 9 | Use the MCP server from Claude Code | Closed |
| 10 | Keep credentials out of shared files | Closed |
| 11 | Automated tests and documentation | Closed |
| 12 | Use a dedicated read-only database user and rotate the root password | New |

## 1. Connect the MCP server to Azure Cosmos DB for MongoDB (vCore)

*State: Closed · Tags: actuvara-db; mcp-server; connectivity*

As a developer, I want the MCP server to connect to the Actuvara cluster using its MongoDB connection string, so that AI assistants can work with the real database (the earlier version only supported the Cosmos DB NoSQL API).

**Acceptance criteria**

- Server connects with pymongo using MONGODB_URI (COSMOS_CONNECTION_STRING accepted as fallback)
- Default database comes from MONGODB_DATABASE, else from the database in the URI (intellidoc)
- Stray quotes / trailing ';' in .env values no longer break the connection
- .env is loaded by the server itself (override=True) so a client can't mangle the '$' in the password
- ping_db returns connected=true and server_info returns hosts and server version (8.0.0) - never credentials
- Every operation is time-boxed (server selection 15s, operation 60s)

## 2. Discover collections and their configuration

*State: Closed · Tags: actuvara-db; mcp-server; discovery*

As a developer / analyst, I want to list databases and collections, find a collection by name and see its settings and indexes, so that I know what exists in the database without opening Compass.

**Acceptance criteria**

- list_databases and list_collections return all databases / all 60 collections (type, view source, capped, validator flag)
- find_collections_like (partial, case-insensitive) and collection_exists (exact) work
- get_collection_details returns options, indexes and size stats (count, size, avg doc size, index count)
- list_indexes returns index name, keys, unique flag and other options

## 3. Infer the fields of each collection

*State: Closed · Tags: actuvara-db; mcp-server; schema*

As a developer / analyst, I want to see which fields a collection has, their data types and how often each appears, so that I understand a schema-less collection's structure.

**Acceptance criteria**

- infer_collection_schema samples documents ($sample, falling back to find) and returns field path, types and presence %
- Nested fields use dots (address.city); fields inside arrays use [] (lines[].amount)
- BSON types are reported clearly (objectId, date, number, string, boolean, array, object, binary, null)
- find_fields_like finds which collections contain a field matching a pattern
- field_exists gives an exact count of documents that have a field across the whole collection

## 4. Infer and verify relationships between collections

*State: Closed · Tags: actuvara-db; mcp-server; relationships*

As a developer / analyst, I want to see how collections link to each other, so that I can understand the data model even though MongoDB has no foreign keys.

**Acceptance criteria**

- Candidate links are found from <name>Id / <name>_id fields (e.g. connector_instance_id -> connector_instances)
- Each link is checked on a sample against the target _id; ids stored as strings are converted to ObjectId first
- Each link reports sample_match_pct and a confidence: confirmed (>=80%), partial, name only, unverified
- Live result: 89 links found - 51 confirmed, 13 partial, 12 name-only, 13 unverified

## 5. Get an overview of the whole database in one call

*State: Closed · Tags: actuvara-db; mcp-server; discovery*

As a developer / analyst, I want one tool that describes the entire database, so that an AI assistant can answer broad questions about the DB quickly.

**Acceptance criteria**

- get_database_overview returns every collection with document count and inferred fields/types
- The same response includes all inferred relationships
- Verified live against all 60 collections

## 6. Read data from collections with my own queries

*State: Closed · Tags: actuvara-db; mcp-server; data-access*

As a developer / analyst, I want to fetch documents from any collection using filters, projections, sorting and aggregations, so that I can answer data questions from Copilot or Claude without writing scripts.

**Acceptance criteria**

- run_find accepts JSON filter, projection, sort and max_rows (MongoDB Extended JSON supported, e.g. {"$oid": "..."})
- run_aggregate accepts a JSON pipeline (match, group, lookup, ...) and always appends a $limit
- get_distinct_values returns the distinct values of a field with counts
- count_documents accepts an optional JSON filter
- Results are returned as plain JSON (ObjectId and dates converted); max 200 rows per call (MCP_MAX_ROWS), 1000 hard cap
- Verified live: run_find on access_requests returns its document

## 7. Enforce read-only access (select only - no insert, update or delete)

*State: Closed · Tags: actuvara-db; mcp-server; security*

As a data owner, I want the server to be unable to change data, so that using AI assistants on the database can never modify or delete records.

**Acceptance criteria**

- The client code never calls insert/update/replace/delete/drop/bulk/index/rename methods (enforced by a test)
- No MCP tool exposes a write operation (enforced by a test)
- query_guard rejects $out and $merge (aggregation writes) at any depth, including inside $lookup
- query_guard rejects $where, $function and $accumulator (server-side JavaScript)
- Verified live: $out / $merge / $where are rejected and no collection is created

## 8. Use the MCP server from GitHub Copilot in VS Code

*State: Closed · Tags: actuvara-db; mcp-server; copilot*

As a developer, I want to use the database tools from Copilot Chat (Agent mode), so that I can explore and query the database from my editor.

**Acceptance criteria**

- .vscode/mcp.json registers the server as actuvara-cosmos-db using the project .venv
- envFile removed so VS Code doesn't alter the connection string
- Copilot can list collections and fetch data after Restart in mcp.json

## 9. Use the MCP server from Claude Code

*State: Closed · Tags: actuvara-db; mcp-server; claude-code*

As a developer, I want to use the same database tools from Claude Code, so that the team can use either assistant with one implementation.

**Acceptance criteria**

- .mcp.json at the project root registers the same server (relative paths, shareable)
- .claude/settings.local.json pre-approves the server locally and is git-ignored
- Verified with an MCP client launched from .mcp.json: 17 tools listed, ping_db and count_documents succeed
- In a new Claude Code session /mcp shows actuvara-cosmos-db connected

## 10. Keep credentials out of shared files

*State: Closed · Tags: actuvara-db; mcp-server; security*

As a security owner, I want connection secrets to stay only in the local .env, so that the database password isn't leaked through the repository.

**Acceptance criteria**

- .env.example contains placeholders only (the real password was removed)
- .env and .claude/settings.local.json are git-ignored
- README explains the .env format (no quotes, no trailing ';', percent-encode special characters)

## 11. Automated tests and documentation

*State: Closed · Tags: actuvara-db; mcp-server; quality*

As a developer, I want offline tests and an up-to-date README, so that changes can be verified without a database and new team members can set the server up.

**Acceptance criteria**

- 27 offline tests pass (query guard, schema helpers, read-only tool list, no write calls in the client)
- README covers setup, Copilot and Claude Code usage, and the full tool list
- requirements.txt uses pymongo; unused Cosmos NoSQL client (nosql_db.py) removed

## 12. Use a dedicated read-only database user and rotate the root password

*State: New · Tags: actuvara-db; mcp-server; security; follow-up*

As a security owner, I want the MCP server to use a database user that only has read rights, so that read-only is enforced by the database itself, not only by our code.

**Acceptance criteria**

- A user with the readAnyDatabase role (or narrower) is created on the cluster by the cluster admin
- .env on every machine uses the read-only user instead of the root login
- The root password (exposed in .env.example and chat) is rotated
- A write attempt with the new user is refused by the database
