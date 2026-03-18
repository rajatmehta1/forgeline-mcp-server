# Blanket MCP Server

Production-grade MCP server for AI code governance. 
Injects organizational coding policies into LLM prompts at generation time — 
so every line of AI-generated code follows your security, quality, and compliance rules.

## Quick Start

### 1. Install

```bash
# Clone and install
cd blanket-mcp
pip install -e ".[dev]"

# Or with Docker
docker compose build
```

### 2. Configure

```bash
cp .env.example .env
# Edit .env with your Neon database URL
```

### 3. Run the schema

```bash
# Run the blanket_v1_schema.sql against your Neon database
psql $BLANKET_DATABASE_URL -f blanket_v1_schema.sql
```

### 4. Create your first org + API key

```sql
-- In psql or Neon SQL Editor:

-- Create your org
INSERT INTO organizations (id, name, slug, plan)
VALUES (gen_random_uuid(), 'My Company', 'my-company', 'team')
RETURNING id;

-- Create a user (use the org id from above)
INSERT INTO users (org_id, email, name, role)
VALUES ('<org_id>', 'you@company.com', 'Volcano', 'owner')
RETURNING id;

-- Generate an API key (save the raw key — you'll only see it once)
-- Raw key example: blk_a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6
INSERT INTO api_keys (org_id, created_by, key_hash, key_prefix, label)
VALUES (
    '<org_id>',
    '<user_id>',
    encode(sha256('blk_a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6'::bytea), 'hex'),
    'blk_a1b2',
    'dev-key'
);

-- Create a project
INSERT INTO projects (org_id, name, slug, language, framework)
VALUES ('<org_id>', 'Backend API', 'backend-api', 'python', 'fastapi')
RETURNING id;

-- Assign template policies to the project
INSERT INTO project_policies (project_id, policy_id)
SELECT '<project_id>', id FROM policies WHERE is_template = true;
```

### 5. Start the server

```bash
# Local dev (no auth)
BLANKET_REQUIRE_AUTH=false python -m blanket_mcp

# Production
python -m blanket_mcp

# Docker
docker compose up -d
```

Server runs at `http://localhost:8000`. Health check at `http://localhost:8000/health`.

---

## Connect to Claude Code

Add to your Claude Code MCP config (`~/.claude/claude_code_config.json`):

```json
{
  "mcpServers": {
    "blanket": {
      "type": "streamableHttp",
      "url": "http://localhost:8000/mcp"
    }
  }
}
```

For remote deployment, replace `localhost:8000` with your server URL.

Claude Code will automatically discover the `get_policies` tool. At the start of every code generation, it calls:

```
get_policies(api_key="blk_...", project="backend-api", language="python", framework="fastapi")
```

And receives the governance rules to follow.

---

## Connect to Cursor

Add to your Cursor MCP settings (`.cursor/mcp.json` in your project root):

```json
{
  "mcpServers": {
    "blanket": {
      "url": "http://localhost:8000/mcp",
      "transport": "streamable-http"
    }
  }
}
```

---

## MCP Tools Reference

### `get_policies` (primary tool)

The main tool. Returns governance policy text that must be applied to generated code.

| Parameter    | Type       | Required | Description                                  |
|-------------|------------|----------|----------------------------------------------|
| `api_key`   | string     | Yes*     | Your Blanket API key                         |
| `project`   | string     | No       | Project slug to scope policies               |
| `language`  | string     | No       | Programming language (python, typescript...) |
| `framework` | string     | No       | Framework (fastapi, nextjs, spring...)       |
| `categories`| string[]   | No       | Filter: security, quality, compliance...     |
| `severities`| string[]   | No       | Filter: error, warning, info                 |
| `tags`      | string[]   | No       | Filter by policy tags                        |
| `source_tool`| string    | No       | Caller identity (claude_code, cursor, api)   |

*Not required when `BLANKET_REQUIRE_AUTH=false`

### `list_projects`

Lists all active projects in the org with policy counts.

### `list_available_policies`

Lists all policies with name, category, severity, and description.

### `get_policy_templates`

Lists built-in Blanket starter templates. No auth required.

---

## Deployment (Hetzner / any VPS)

```bash
# 1. SSH into your server
ssh root@your-server

# 2. Clone the repo
git clone https://github.com/your-org/blanket-mcp.git
cd blanket-mcp

# 3. Set environment
cp .env.example .env
nano .env  # Add your Neon DATABASE_URL

# 4. Build and run
docker compose up -d

# 5. Verify
curl http://localhost:8000/health
# {"status": "healthy"}
```

### Behind Nginx (recommended)

```nginx
server {
    listen 443 ssl;
    server_name mcp.blanket.com;

    ssl_certificate     /etc/letsencrypt/live/mcp.blanket.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/mcp.blanket.com/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300s;
    }
}
```

---

## Architecture

```
Claude Code / Cursor
        │
        │  MCP (streamable-http)
        ▼
┌──────────────────┐
│  FastMCP Server   │
│  (blanket-mcp)   │
├──────────────────┤
│  Auth (API key)  │──→ api_keys table
│  Policy Engine   │──→ policies + project_policies
│  Enforcement Log │──→ enforcement_log table
└──────────────────┘
        │
        ▼
   Neon PostgreSQL
```

## License

Proprietary — Blanket / Volcano