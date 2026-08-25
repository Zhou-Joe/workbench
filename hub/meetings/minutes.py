"""Meeting minutes → markdown document for send-to-phase.

Format mirrors the proven MD export from MeetingAssistant: summary first,
then the transcript grouped by speaker with translations as blockquotes.
"""

from __future__ import annotations

from django.utils.text import slugify


def build_minutes_markdown(meeting, utterances) -> str:
    lines: list[str] = [f"# {meeting.title}", ""]
    bits = [meeting.started_at.strftime("%Y-%m-%d %H:%M")]
    if meeting.series_id:
        bits.append(f"series: {meeting.series.title}")
    if meeting.ended_at:
        mins = int((meeting.ended_at - meeting.started_at).total_seconds() // 60)
        bits.append(f"{mins} min")
    lines += [" · ".join(bits), ""]
    if meeting.summary:
        lines += ["## Summary", "", meeting.summary, ""]

    lines += ["## Transcript", ""]
    current_speaker = None
    for utt in utterances:
        speaker = utt.speaker_label or "speaker_0"
        if speaker != current_speaker:
            lines += [f"**{speaker}**", ""]
            current_speaker = speaker
        lines.append(utt.text)
        if utt.translation:
            lines += ["", f"> {utt.translation}"]
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def minutes_filename(meeting) -> str:
    date = meeting.started_at.strftime("%Y-%m-%d")
    slug = slugify(meeting.title) or "meeting"
    return f"meeting-{date}-{slug[:80]}.md"
