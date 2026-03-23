# Multi-User Troop Dashboard Web App - Implementation Plan

## Architecture

**Framework:** FastAPI with JWT authentication
**App Database:** SQLite (`app.db`) for users, troops, memberships
**Troop Data:** Separate `.db` files per troop (synced externally, read-only by webapp)
**Dashboard:** Adapted `dashboard.html` that calls server-side API instead of client-side sql.js

## App Database Schema (`app.db`)

```sql
-- Users table
CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT UNIQUE NOT NULL,
    display_name TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Troops table
CREATE TABLE troops (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    db_path TEXT NOT NULL,          -- path to troop's .db file
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Troop memberships (with approval workflow)
CREATE TABLE troop_memberships (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    troop_id INTEGER NOT NULL REFERENCES troops(id),
    status TEXT NOT NULL DEFAULT 'pending',  -- 'pending', 'approved'
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, troop_id)
);

-- Password reset tokens
CREATE TABLE password_reset_tokens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    token TEXT UNIQUE NOT NULL,
    expires_at TIMESTAMP NOT NULL,
    used INTEGER DEFAULT 0
);
```

## API Endpoints

### Authentication
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/auth/register` | Create account (email, name, password) |
| POST | `/api/auth/login` | Login, returns JWT access + refresh tokens |
| POST | `/api/auth/refresh` | Refresh access token |
| POST | `/api/auth/reset-password/request` | Generate reset token (returned in response; if SMTP configured, emailed) |
| POST | `/api/auth/reset-password/confirm` | Reset password with token |
| GET | `/api/auth/me` | Get current user info + troop membership |

### Troops & Membership
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/troops` | List all troops (for registration flow) |
| POST | `/api/troops` | Create new troop (user auto-approved as member) |
| GET | `/api/troops/mine` | Get current user's troop details |
| GET | `/api/troops/members` | List members of user's troop |
| GET | `/api/troops/pending` | List pending join requests for user's troop |
| POST | `/api/troops/members/{user_id}/approve` | Approve a pending member |
| DELETE | `/api/troops/members/{user_id}` | Remove a member from the troop |

### Dashboard Data
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/troop/query` | Execute read-only SQL against user's troop .db |

The `/api/troop/query` endpoint is the pragmatic approach - the dashboard currently runs ~50+ different SQL queries via sql.js. Rather than creating 50 individual REST endpoints, this single endpoint:
- Requires authentication
- Looks up the user's approved troop and its `.db` path
- Opens the `.db` read-only
- Only allows SELECT statements
- Returns results as JSON

This minimizes dashboard changes while enforcing troop isolation server-side.

## File Structure

```
webapp/
├── __init__.py
├── main.py              # FastAPI app, startup, middleware
├── config.py            # Settings (SECRET_KEY, DB paths, etc.)
├── database.py          # App DB connection and init
├── models.py            # Pydantic models (request/response schemas)
├── auth.py              # JWT token creation/validation, password hashing
├── routes/
│   ├── __init__.py
│   ├── auth.py          # Auth endpoints
│   ├── troops.py        # Troop management endpoints
│   └── dashboard.py     # Dashboard query endpoint
├── dependencies.py      # FastAPI dependencies (get_current_user, etc.)
├── static/
│   └── dashboard.html   # Adapted dashboard (fetches via API)
└── templates/
    ├── login.html
    ├── register.html
    └── troop_setup.html # Create or join troop after registration
```

## Dashboard Adaptation

Minimal changes to `dashboard.html`:
1. Remove sql.js loading and file picker
2. Replace `q(sql)` and `q1(sql)` helpers with `fetch('/api/troop/query', {body: sql})`
3. Add JWT token management (store in memory/localStorage, attach to requests)
4. Add login redirect if not authenticated
5. Remove Settings tab file-picker UI (DB is managed server-side)

## Implementation Steps

1. **Set up FastAPI project structure** - Add dependencies to pyproject.toml, create webapp/ package
2. **Build app database layer** - Schema creation, connection management
3. **Implement authentication** - Registration, login, JWT, password reset
4. **Implement troop management** - Create/join troop, approval workflow, member removal
5. **Implement dashboard query endpoint** - Read-only SQL proxy scoped to user's troop
6. **Adapt dashboard.html** - Replace sql.js with API calls, add auth flow
7. **Add frontend pages** - Login, register, troop setup (simple HTML/CSS, no framework)
8. **Wire up static file serving** - Serve dashboard and auth pages from FastAPI
9. **Test end-to-end flow** - Registration → troop join → approval → dashboard access
