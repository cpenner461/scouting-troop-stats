"""Troop-wide analytical queries."""


def most_common_incomplete_merit_badges(conn, limit=20, eagle_only=False):
    """Merit badges NOT completed by the most scouts.

    Shows which MBs would benefit the most scouts if offered as a
    troop activity.
    """
    eagle_filter = "AND mb.is_eagle_required = 1" if eagle_only else ""
    return conn.execute(
        f"""
        SELECT
            mb.name AS merit_badge,
            mb.is_eagle_required,
            COUNT(s.user_id) AS scouts_needing,
            (SELECT COUNT(*) FROM scouts) AS total_scouts,
            ROUND(COUNT(s.user_id) * 100.0
                  / MAX((SELECT COUNT(*) FROM scouts), 1), 1) AS pct_needing
        FROM merit_badges mb
        CROSS JOIN scouts s
        LEFT JOIN scout_merit_badges smb
            ON smb.scout_user_id = s.user_id
            AND smb.merit_badge_name = mb.name
            AND smb.status = 'completed'
        WHERE smb.id IS NULL
          AND mb.active = 1
          {eagle_filter}
        GROUP BY mb.name
        ORDER BY scouts_needing DESC, mb.is_eagle_required DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()


def scouts_closest_to_next_rank(conn):
    """Which scouts are closest to their next rank?

    For each scout, finds next rank in the Scouts BSA progression
    and counts remaining top-level requirements.
    """
    return conn.execute(
        """
        WITH next_rank AS (
            SELECT
                s.user_id,
                COALESCE(s.first_name, '') || ' ' || COALESCE(s.last_name, '') AS scout_name,
                s.current_rank_id,
                cr.name AS current_rank,
                nr.id AS next_rank_id,
                nr.name AS next_rank_name
            FROM scouts s
            LEFT JOIN ranks cr ON cr.id = s.current_rank_id
            INNER JOIN ranks nr ON nr.program_id = 2
                AND nr.level = COALESCE(cr.level, 0) + 1
        ),
        req_counts AS (
            SELECT
                nr.user_id,
                nr.scout_name,
                nr.current_rank,
                nr.next_rank_name,
                COUNT(r.id) AS total_requirements,
                COALESCE(SUM(CASE WHEN src.completed = 1 THEN 1 ELSE 0 END), 0)
                    AS completed_requirements
            FROM next_rank nr
            INNER JOIN requirements r ON r.rank_id = nr.next_rank_id
                AND r.required = 1
                AND r.parent_requirement_id IS NULL
            LEFT JOIN scout_requirement_completions src
                ON src.scout_user_id = nr.user_id
                AND src.requirement_id = r.id
            GROUP BY nr.user_id
        )
        SELECT
            scout_name,
            current_rank,
            next_rank_name,
            total_requirements,
            completed_requirements,
            total_requirements - completed_requirements AS remaining,
            ROUND(completed_requirements * 100.0
                  / MAX(total_requirements, 1), 1) AS pct_complete
        FROM req_counts
        WHERE total_requirements > 0
        ORDER BY remaining ASC, pct_complete DESC
        """
    ).fetchall()


def requirement_completion_matrix(conn, rank_id):
    """For a rank, which requirements are most commonly incomplete?

    Helps plan meetings around specific skill areas that the most
    scouts still need.
    """
    return conn.execute(
        """
        SELECT
            r.requirement_number,
            COALESCE(r.short, SUBSTR(r.name, 1, 60)) AS requirement_desc,
            (SELECT COUNT(*) FROM scouts) AS total_scouts,
            COALESCE(SUM(CASE WHEN src.completed = 1 THEN 1 ELSE 0 END), 0)
                AS scouts_completed,
            (SELECT COUNT(*) FROM scouts)
                - COALESCE(SUM(CASE WHEN src.completed = 1 THEN 1 ELSE 0 END), 0)
                AS scouts_needing,
            ROUND(
                ((SELECT COUNT(*) FROM scouts)
                 - COALESCE(SUM(CASE WHEN src.completed = 1 THEN 1 ELSE 0 END), 0))
                * 100.0 / MAX((SELECT COUNT(*) FROM scouts), 1), 1
            ) AS pct_incomplete
        FROM requirements r
        LEFT JOIN scout_requirement_completions src
            ON src.requirement_id = r.id
            AND src.completed = 1
        WHERE r.rank_id = ?
          AND r.required = 1
          AND r.parent_requirement_id IS NULL
        GROUP BY r.id
        ORDER BY pct_incomplete DESC
        """,
        (rank_id,),
    ).fetchall()


def per_scout_summary(conn):
    """Summary for each scout: rank, MBs earned, Eagle MBs, in-progress."""
    return conn.execute(
        """
        SELECT
            COALESCE(s.first_name, '') || ' ' || COALESCE(s.last_name, '') AS scout_name,
            COALESCE(cr.name, '--') AS current_rank,
            (SELECT COUNT(*) FROM scout_merit_badges smb
             WHERE smb.scout_user_id = s.user_id
               AND smb.status = 'completed') AS total_mbs_earned,
            (SELECT COUNT(*) FROM scout_merit_badges smb
             INNER JOIN merit_badges mb ON mb.name = smb.merit_badge_name
             WHERE smb.scout_user_id = s.user_id
               AND smb.status = 'completed'
               AND mb.is_eagle_required = 1) AS eagle_mbs_earned,
            (SELECT COUNT(*) FROM scout_merit_badges smb
             WHERE smb.scout_user_id = s.user_id
               AND smb.status = 'in_progress') AS mbs_in_progress,
            s.last_synced_at
        FROM scouts s
        LEFT JOIN ranks cr ON cr.id = s.current_rank_id
        ORDER BY COALESCE(cr.level, 0) DESC, scout_name
        """
    ).fetchall()


def mb_requirement_detail(conn, merit_badge_name=None):
    """Show incomplete MB requirements across scouts.

    For each in-progress MB requirement, shows how many scouts still need it.
    Optionally filter to a single merit badge by name.
    """
    name_filter = ""
    params = ()
    if merit_badge_name:
        name_filter = "AND smb.merit_badge_name = ?"
        params = (merit_badge_name,)

    return conn.execute(
        f"""
        SELECT
            smb.merit_badge_name,
            mr.requirement_number,
            SUBSTR(mr.name, 1, 60) AS requirement_desc,
            COUNT(DISTINCT smb.scout_user_id) AS scouts_working,
            SUM(CASE WHEN smrc.completed = 1 THEN 1 ELSE 0 END) AS scouts_done,
            COUNT(DISTINCT smb.scout_user_id)
                - SUM(CASE WHEN smrc.completed = 1 THEN 1 ELSE 0 END) AS scouts_needing,
            ROUND(
                SUM(CASE WHEN smrc.completed = 1 THEN 1 ELSE 0 END) * 100.0
                / MAX(COUNT(DISTINCT smb.scout_user_id), 1), 1
            ) AS pct_complete
        FROM mb_requirements mr
        INNER JOIN scout_mb_requirement_completions smrc
            ON smrc.mb_requirement_id = mr.id
        INNER JOIN scout_merit_badges smb
            ON smb.scout_user_id = smrc.scout_user_id
            AND smb.status = 'in_progress'
            AND smrc.mb_api_id IN (
                SELECT smb2.mb_api_id
                FROM scout_merit_badges smb2
                WHERE smb2.scout_user_id = smb.scout_user_id
                  AND smb2.merit_badge_name = smb.merit_badge_name
            )
        WHERE mr.parent_requirement_id IS NULL
          {name_filter}
        GROUP BY smb.merit_badge_name, mr.id
        ORDER BY smb.merit_badge_name, mr.sort_order, mr.requirement_number
        """,
        params,
    ).fetchall()


def optimal_group_activities(conn, min_pct=50.0):
    """Activities where >= min_pct% of the troop would benefit.

    This is the key query for planning troop meetings: which Eagle-required
    merit badges does the largest fraction of the troop still need?
    """
    return conn.execute(
        """
        SELECT
            mb.name AS activity_name,
            mb.is_eagle_required,
            COUNT(s.user_id) AS scouts_benefiting,
            (SELECT COUNT(*) FROM scouts) AS total_scouts,
            ROUND(COUNT(s.user_id) * 100.0
                  / MAX((SELECT COUNT(*) FROM scouts), 1), 1) AS pct_benefiting
        FROM merit_badges mb
        CROSS JOIN scouts s
        LEFT JOIN scout_merit_badges smb
            ON smb.scout_user_id = s.user_id
            AND smb.merit_badge_name = mb.name
            AND smb.status = 'completed'
        WHERE smb.id IS NULL
          AND mb.active = 1
        GROUP BY mb.name
        HAVING pct_benefiting >= ?
        ORDER BY mb.is_eagle_required DESC, pct_benefiting DESC
        """,
        (min_pct,),
    ).fetchall()
