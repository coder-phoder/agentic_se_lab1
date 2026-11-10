# SG-02: Page metadata

Status: ACTIVE (version 2)
Category: Structure

Every team website MUST set the following metadata in the document head.

## Title
The page title MUST have the format:

    Team <group name> | Agentic SE Lab

Example: `Team Null Pointers | Agentic SE Lab`. Use a vertical bar, not a dash.
The group name in the title MUST match the group name shown in the page header.

## Language
The root `<html>` element MUST declare English as the page language: `lang="en"`.
Even if some content is written in German, the declared language stays English.

## Other metadata
- The character set MUST be UTF-8.
- A `<meta name="viewport">` tag MUST be present, see the responsive documents.
- A `<meta name="description">` SHOULD contain one sentence about the team.
