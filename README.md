# Workflow

Pipeline de producción de videos para YouTube: generación de imágenes por IA, transcripción de audio y renderizado Ken Burns.

## Arquitectura

```
┌──────────┐     ┌───────────┐     ┌──────────────┐
│ Extension│ ←── │  Backend  │ ←── │   Frontend   │
│  Chrome  │ WS  │  FastAPI  │ API │  React/Vite  │
│  MV3     │ ──→ │  :8000    │ ──→ │   :5173      │
└──────────┘     │  Bridge   │     └──────────────┘
                 │  WS :8766 │
                 └───────────┘
```

### Componentes

| Capa | Tecnología | Puerto | Propósito |
|------|-----------|--------|-----------|
| **backend/** | Python 3.14, FastAPI, faster-whisper, FFmpeg | `:8000` | API REST, orquestador, transcripción, render |
| **frontend/** | React 19, Vite 8, TypeScript, Tailwind | `:5173` | Dashboard, editor de fragmentos, control de pipeline |
| **extension/** | Chrome MV3, JS vanilla | — | Bridge WebSocket con Google Flow para generación de imágenes |

## Requisitos

- Python 3.14+
- [bun](https://bun.sh) 1.x
- FFmpeg (con `ffprobe`)
- Chrome/Chromium (para la extensión)

## Setup

```bash
# Backend
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload

# Frontend
cd frontend
bun install
bun run dev

# Extensión
# chrome://extensions → "Cargar extensión sin empaquetar" → seleccionar extension/
```

## Flujo de trabajo

1. **Crear canal y proyecto** desde el Dashboard
2. **Subir audio** (`audio.mp3`) y **guión** (`text.txt`) a la carpeta del proyecto
3. **Editar fragmentos** — el splitter divide el texto en segmentos de 15-21 palabras
4. **Generar prompts** — cada fragmento recibe un prompt de imagen descriptivo
5. **Generar imágenes** — la extensión envía los prompts a Google Flow vía WebSocket
6. **Transcribir** — Whisper transcribe el audio con timestamps por palabra
7. **Renderizar** — Ken Burns combina imágenes + audio + subtítulos en un video MP4

### Workflow completo (1 clic)

El orquestador ejecuta Generate → Transcribe → Render en secuencia, omitiendo pasos ya completados (ej. imágenes ya generadas no se regeneran).

## Estructura del proyecto

```
workflow/
├── backend/
│   └── app/
│       ├── main.py              # FastAPI app, lifespan, CORS
│       ├── config.py            # Settings (modelo, puertos, etc.)
│       ├── models/              # Pydantic models
│       ├── routers/             # API endpoints
│       │   ├── channels.py      # Canales de YouTube
│       │   ├── projects.py      # CRUD de proyectos
│       │   ├── fragments.py     # Fragmentos/prompts
│       │   ├── images.py        # Generación de imágenes
│       │   ├── transcribe.py    # Transcripción Whisper
│       │   ├── render.py        # Render Ken Burns
│       │   └── workflow.py      # Orquestador (SSE)
│       ├── services/
│       │   ├── forge_bridge.py  # WS bridge con extensiones
│       │   ├── orchestrator.py  # Pipeline completo
│       │   ├── whisper_pipeline.py  # Transcripción + alineación
│       │   └── kenburns.py      # Renderizado de video
│       └── core/
│           ├── sse.py           # Server-Sent Events
│           └── task_queue.py    # Thread pool
├── frontend/
│   └── src/
│       ├── App.tsx              # Router, sidebar, layout
│       ├── pages/               # Dashboard, Editor, Images, etc.
│       ├── components/          # UI components
│       ├── api/client.ts        # API client
│       └── hooks/               # Custom hooks
├── extension/
│   ├── manifest.json            # Chrome MV3 manifest
│   ├── bridge.js                # WS bridge (ISOLATED world)
│   └── token-gen.js             # reCAPTCHA + fetch (MAIN world)
└── .gitignore
```

## Límites conocidos

- **Google Flow**: 100 imágenes/día por cuenta
- **faster-whisper**: modelo `small` en CPU (~5x tiempo real)
- **Render**: FFmpeg en CPU, videos de hasta ~10 min

## Roadmap (Must Have / TODO)

- [ ] **Diarización de hablantes** — identificar quién habla en cada fragmento (ej. llamadas cliente/agente) integrando `pyannote.audio` al pipeline de transcripción:
  - Modelo: `pyannote/speaker-diarization-community-1` con GPU CUDA (probado en RTX 3050, ~30s por 10 min de audio).
  - Requisitos: token de Hugging Face (`hf auth login`) y aceptar términos de los modelos gated `pyannote/speaker-diarization-community-1` y `pyannote/segmentation-3.0`.
  - Audio telefónico μ-law 8kHz soportado: decodificar con PyAV a 16kHz (`torchcodec` requiere FFmpeg *shared*, alternativa: pre-cargar waveform en memoria y no pasar rutas de archivo).
  - Script base funcional: `backend/scripts/diarize_speakers.py` — asigna speaker por palabra (máximo solape temporal sobre `script.json`) y genera `.speakers.txt/.speakers.srt/.speakers.json`.
  - **Calidad máxima**: usar `large-v3` con `beam_size=5`, `language="es"`, `condition_on_previous_text=False`.
  - **Transcripción guiada por diarización** (evita fragmentos perdidos por el VAD de Whisper): tomar los turnos de pyannote como regiones de voz (+0.3s de pad, fusionar huecos <1s), transcribir cada región sin VAD y re-diarizar para etiquetar. Script: `backend/scripts/transcribe_diar_guided.py`.
  - Pendiente: endpoint en `routers/transcribe.py`, UI para renombrar hablantes y render de subtítulos con color/estilo por locutor.
