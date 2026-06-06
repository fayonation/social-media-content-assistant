# Bundled fonts

Used by `pipeline/overlay.py` for headline text on images (Latin and Arabic RTL).

| File | Use |
|------|-----|
| `NotoSans.ttf` | Latin headlines |
| `NotoNaskhArabic.ttf` | Arabic / RTL headlines |

Both are **Noto** fonts from [Google Noto Fonts](https://github.com/notofonts/noto-fonts) (SIL Open Font License).

If these files are missing after clone, run:

```bash
./scripts/download-fonts.sh
```

`./serve.sh` also runs that script automatically when fonts are absent.
