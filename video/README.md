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

The Fire TV track requires the product running on a Fire TV device or in the
official Fire TV emulator. That means the recording cannot be made from a desktop
browser: it has to show the APK from `.github/workflows/android.yml` installed on
a device or emulator, driven by a remote or by `adb shell input keyevent`, with
the D-pad moving focus and the governed rollback being confirmed on screen.

`docs/FIRE_TV_BUILD.md` has the commands to get to that state.
