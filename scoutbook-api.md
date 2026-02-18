# Scoutbook Plus API Reference

Base URL: `https://api.scouting.org`

## Youth Advancement Endpoints

These endpoints are user-specific. The `{userId}` is the numeric ID found in the youth profile URL:
`https://advancements.scouting.org/youthProfile/{userId}`

### Ranks
```
GET /advancements/v2/youth/{userId}/ranks
```
Returns the rank advancement history for a specific youth member.

### Merit Badges
```
GET /advancements/v2/youth/{userId}/meritBadges
```
Returns earned and in-progress merit badges for a specific youth member.

### Awards
```
GET /advancements/v2/youth/{userId}/awards
```
Returns awards earned by a specific youth member.

### Activity Summary
```
GET /advancements/v2/{userId}/userActivitySummary
```
Returns a summary of the youth member's activity.

### Leadership Position History
```
GET /advancements/youth/{userId}/leadershipPositionHistory?summary=true
```
Returns leadership position history for a specific youth member.

---

## Reference / Lookup Endpoints

These are static, not user-specific.

### Active Ranks List
```
GET /advancements/ranks?status=active
```
Returns all active rank definitions.

### Merit Badges List
```
GET /advancements/meritBadges
```
Returns all merit badge definitions.

### Awards List
```
GET /advancements/awards
```
Returns all award definitions.

### Adventures List
```
GET /advancements/adventures
```
Returns all adventure definitions.

### Super Nova Electives List
```
GET /advancements/ssElectives
```
Returns Super Nova / elective definitions.

### Leadership Positions List
```
GET /lookups/advancements/positions
```
Returns all leadership position definitions.

---

## Person / Profile Endpoints

### Youth Person Profile
```
GET /persons/v2/{userId}/personprofile
```
Returns profile data for a youth member by numeric user ID.

### Person Profile (by GUID)
```
GET /persons/v2/{personGuid}/personprofile
```
Returns profile data using the person's GUID (UUID format).

---

## Organization Endpoints

### Unit Adults
```
GET /organizations/v2/units/{organizationGuid}/adults
```
Returns all adult members for a given unit.

### Organization Profile
```
GET /organizations/v2/{organizationGuid}/profile
```
Returns profile info for a given organization.

---

## Notes

- Authentication is required (session cookie / bearer token from the Scoutbook Plus web session).
- The `organizationGuid` is a UUID that identifies the unit, e.g. `BEA2F123-1427-419F-8A70-65FA38517D9E`. It appears as a query parameter in roster URLs:
  `https://advancements.scouting.org/youthProfile/{userId}?organizationGuid={organizationGuid}`
- The `userId` is a numeric string (e.g. `9268150`).
- The `personGuid` is a UUID used in some person-level endpoints and is distinct from the numeric `userId`.
