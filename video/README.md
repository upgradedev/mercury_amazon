# Video plan

**No video has been recorded.** Nothing in this directory is a record of a take.

`narration.json` and `cue_sheet.json` are a shot plan: what would be said, in what
order, and roughly how long each beat should run. They exist so a recording can be
made from a script rather than improvised, and so a single beat can be re-recorded
without redoing the rest.

The subtitle files that used to sit alongside them have been deleted. A subtitle
file asserts timing against a picture, and there is no picture, so they attested
something that did not exist.

Readiness gates E2 (narration and picture in sync) and E4 (public video of the
running product) both fail, correctly, until a video exists.

## What a recording would have to show

The Fire TV track requires the product running on an allowed target. The event's
official FAQ accepts Android TV Emulator or Fire TV/Vega simulator and does not
require physical hardware. The final recording should therefore use the exact APK
from `.github/workflows/android-tv-emulator.yml`, driven by D-pad key events, with
the loaded endpoint and native journey logs matching the retained receipt. The
surface being recorded is a D-pad and a screen; nothing in it listens for speech.

`docs/FIRE_TV_BUILD.md` has the commands to get to that state.
