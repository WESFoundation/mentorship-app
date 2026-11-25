"""
Cloud Voice Feedback Structuring Service & Queue
Supports Groq Whisper Turbo, Azure OpenAI, Anthropic, and OpenAI fallback.
Runs a background sequential FIFO queue worker to keep Flask server memory ultra-low (<40MB).
"""

import os
import time
import json
import uuid
import queue
import logging
import threading
import urllib.request
import urllib.error

try:
    import requests
except ImportError:
    requests = None

logger = logging.getLogger(__name__)

# Keys from environment (Coolify / .env)
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "").strip()
GROQ_STT_API_KEY = os.environ.get("GROQ_STT_API_KEY", "").strip()
AZURE_OPENAI_API_KEY = (
    os.environ.get("AZURE_OPENAI_API_KEY", "").strip()
    or os.environ.get("AZURE_AI_FOUNDRY_API_KEY", "").strip()
)
AZURE_OPENAI_ENDPOINT = (
    os.environ.get("AZURE_OPENAI_ENDPOINT", "").strip()
    or os.environ.get("AZURE_AI_FOUNDRY_ENDPOINT", "").strip()
)
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
TRANSCRIBE_API_KEY = os.environ.get("TRANSCRIBE_API_KEY", "").strip()

# Default models
GROQ_STT_MODEL = os.environ.get("GROQ_STT_MODEL", "whisper-large-v3-turbo")
GROQ_LLM_MODEL = os.environ.get("GROQ_LLM_MODEL", "qwen/qwen3.8-27b")
AZURE_OPENAI_DEPLOYMENT = (
    os.environ.get("AZURE_OPENAI_DEPLOYMENT", "").strip()
    or os.environ.get("AZURE_AI_FOUNDRY_MODEL", "").strip()
    or "model-router"
)

# Task queue and thread-safe store
task_queue = queue.Queue()
task_results = {}
task_results_lock = threading.Lock()


def get_groq_api_key():
    return os.environ.get("GROQ_API_KEY", "").strip() or GROQ_API_KEY


def get_groq_stt_api_key():
    """Returns Groq API key dedicated to Whisper STT transcription only."""
    return (
        os.environ.get("GROQ_STT_API_KEY", "").strip()
        or GROQ_STT_API_KEY
        or get_groq_api_key()
    )


def get_azure_config():
    """Returns (api_key, endpoint, deployment) dynamically from environment."""
    key = (
        os.environ.get("AZURE_OPENAI_API_KEY", "").strip()
        or os.environ.get("AZURE_AI_FOUNDRY_API_KEY", "").strip()
        or AZURE_OPENAI_API_KEY
    )
    endpoint = (
        os.environ.get("AZURE_OPENAI_ENDPOINT", "").strip()
        or os.environ.get("AZURE_AI_FOUNDRY_ENDPOINT", "").strip()
        or AZURE_OPENAI_ENDPOINT
    )
    deployment = (
        os.environ.get("AZURE_OPENAI_DEPLOYMENT", "").strip()
        or os.environ.get("AZURE_AI_FOUNDRY_MODEL", "").strip()
        or AZURE_OPENAI_DEPLOYMENT
        or "model-router"
    )
    return key, endpoint, deployment


def is_ai_configured():
    azure_key, azure_endpoint, _ = get_azure_config()
    return bool(get_groq_stt_api_key() or get_groq_api_key() or (azure_key and azure_endpoint) or ANTHROPIC_API_KEY or TRANSCRIBE_API_KEY)


def transcribe_audio_cloud(audio_bytes: bytes, filename: str = "feedback.webm", mimetype: str = "audio/webm") -> str:
    """Sends audio to Groq Whisper Turbo (or OpenAI/Azure fallback) for fast transcription."""
    groq_key = get_groq_stt_api_key()
    if groq_key:
        boundary = f"----WebKitFormBoundary{uuid.uuid4().hex[:16]}"
        body = bytearray()
        
        # model field
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(b'Content-Disposition: form-data; name="model"\r\n\r\n')
        body.extend(f"{GROQ_STT_MODEL}\r\n".encode())
        
        # response format
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(b'Content-Disposition: form-data; name="response_format"\r\n\r\n')
        body.extend(b"json\r\n")

        # file field
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode())
        body.extend(f"Content-Type: {mimetype or 'audio/webm'}\r\n\r\n".encode())
        body.extend(audio_bytes)
        body.extend(b"\r\n")
        body.extend(f"--{boundary}--\r\n".encode())

        req = urllib.request.Request(
            "https://api.groq.com/openai/v1/audio/transcriptions",
            data=bytes(body),
            headers={
                "Authorization": f"Bearer {groq_key}",
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "User-Agent": "WES-Mentorship-CloudAudio/1.0"
            }
        )
        try:
            with urllib.request.urlopen(req, timeout=45) as resp:
                data = json.loads(resp.read().decode())
                text = (data.get("text") or "").strip()
                if not text:
                    raise ValueError("No speech detected in audio")
                return text
        except urllib.error.HTTPError as err:
            err_msg = err.read().decode(errors="ignore")
            logger.error(f"Groq Whisper HTTP error {err.code}: {err_msg}")
            raise RuntimeError(f"Groq transcription error ({err.code}): {err_msg[:200]}")
        except Exception as e:
            logger.error(f"Groq Whisper network error: {e}")
            raise

    # 2. Try Azure OpenAI Whisper if deployed on resource
    azure_key, azure_endpoint, _ = get_azure_config()
    if azure_key and azure_endpoint:
        whisper_dep = os.environ.get("AZURE_WHISPER_DEPLOYMENT", "whisper").strip()
        ep_clean = azure_endpoint.rstrip("/")
        base_host = ep_clean.split("/openai")[0] if "/openai" in ep_clean else ep_clean
        whisper_url = f"{base_host}/openai/deployments/{whisper_dep}/audio/transcriptions?api-version=2024-02-15-preview"
        
        boundary = f"----WebKitFormBoundary{uuid.uuid4().hex[:16]}"
        body = bytearray()
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(b'Content-Disposition: form-data; name="file"; filename="recording.webm"\r\n')
        body.extend(f"Content-Type: {mimetype or 'audio/webm'}\r\n\r\n".encode())
        body.extend(audio_bytes)
        body.extend(b"\r\n")
        body.extend(f"--{boundary}--\r\n".encode())

        req = urllib.request.Request(
            whisper_url,
            data=bytes(body),
            headers={
                "api-key": azure_key,
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "User-Agent": "WES-Mentorship-CloudAudio/1.0"
            }
        )
        try:
            with urllib.request.urlopen(req, timeout=45) as resp:
                data = json.loads(resp.read().decode())
                text = (data.get("text") or "").strip()
                if text:
                    return text
        except Exception as e:
            logger.info(f"Azure OpenAI Whisper STT attempt ({whisper_dep}): {e}")

    # 3. Fallback to Azure Cognitive Services Speech STT if Azure key is available
    if azure_key:
        region = os.environ.get("AZURE_SPEECH_REGION", "southindia").strip()
        stt_url = f"https://{region}.stt.speech.microsoft.com/speech/recognition/conversation/cognitiveservices/v1?language=en-US"
        m = (mimetype or "").lower()
        if "webm" in m:
            ct = "audio/webm; codecs=opus"
        elif "ogg" in m:
            ct = "audio/ogg; codecs=opus"
        elif "wav" in m:
            ct = "audio/wav; codecs=audio/pcm; samplerate=16000"
        else:
            ct = "audio/webm; codecs=opus"

        req = urllib.request.Request(
            stt_url,
            data=audio_bytes,
            headers={
                "Ocp-Apim-Subscription-Key": azure_key,
                "Content-Type": ct,
                "Accept": "application/json",
                "User-Agent": "WES-Mentorship-CloudAudio/1.0"
            }
        )
        try:
            with urllib.request.urlopen(req, timeout=45) as resp:
                data = json.loads(resp.read().decode())
                text = (data.get("DisplayText") or data.get("Text") or "").strip()
                if text:
                    return text
        except urllib.error.HTTPError as err:
            err_msg = err.read().decode(errors="ignore")
            logger.warning(f"Azure Speech STT HTTP error {err.code}: {err_msg}")
        except Exception as e:
            logger.warning(f"Azure Speech STT network error: {e}")

    # 4. Fallback to legacy transcribe_audio if configured
    transcribe_key = os.environ.get("TRANSCRIBE_API_KEY")
    if transcribe_key:
        base = (os.environ.get("TRANSCRIBE_API_BASE") or "https://api.openai.com/v1").rstrip("/")
        boundary = f"----WebKitFormBoundary{uuid.uuid4().hex[:16]}"
        body = bytearray()
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(b'Content-Disposition: form-data; name="model"\r\n\r\n')
        body.extend(f"{os.environ.get('TRANSCRIBE_MODEL', 'whisper-1')}\r\n".encode())
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode())
        body.extend(f"Content-Type: {mimetype or 'audio/webm'}\r\n\r\n".encode())
        body.extend(audio_bytes)
        body.extend(b"\r\n")
        body.extend(f"--{boundary}--\r\n".encode())

        req = urllib.request.Request(
            f"{base}/audio/transcriptions",
            data=bytes(body),
            headers={
                "Authorization": f"Bearer {transcribe_key}",
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "User-Agent": "WES-Mentorship-CloudAudio/1.0"
            }
        )
        with urllib.request.urlopen(req, timeout=45) as resp:
            data = json.loads(resp.read().decode())
            text = (data.get("text") or "").strip()
            if not text:
                raise ValueError("No speech detected in audio")
            return text

    raise ValueError("Speech-to-text not available. Add GROQ_API_KEY (free at console.groq.com) or deploy 'whisper' model in Microsoft Foundry.")


def structure_feedback_cloud(transcript: str, form_type: str = "generic", task_title: str = "", task_description: str = "") -> dict:
    """
    Structures the transcript into form fields using Groq Qwen / Llama or Azure OpenAI / Foundry.
    Handles different form types: mentee_reflection, mentor_reflection, mentor_rating, institution_reflection, generic.
    Includes task title and description for contextual understanding if provided.
    """
    groq_key = get_groq_api_key()

    # Form schemas and field specifications
    form_schemas = {
        "mentee_reflection": {
            "fields": {
                "text": "Detailed descriptive sentences on what was learned and what went well",
                "challenges": "Detailed descriptive sentences on difficulties or challenges faced",
                "nextSteps": "Actionable next steps or recommendations",
                "extra": "Any additional thoughts or context"
            },
            "desc": "mentee self-reflection on a mentoring task"
        },
        "mentor_reflection": {
            "fields": {
                "text": "Detailed descriptive sentences on how the session/task went and key discussion points",
                "extra": "Additional notes, recommendations, or observations"
            },
            "desc": "mentor reflection on a mentoring session"
        },
        "mentor_rating": {
            "fields": {
                "rating": "Integer rating between 1 and 5",
                "feedback": "Overall evaluation of task completion and mentee progress",
                "strengths": "Observed strengths, accomplishments, and areas for improvement"
            },
            "desc": "mentor task review and rating"
        },
        "institution_reflection": {
            "fields": {
                "text": "Evaluation of mentee progress or session outcomes",
                "notes": "Internal administrative notes or follow-up items"
            },
            "desc": "institution coordinator task evaluation"
        },
        "generic": {
            "fields": {
                "rating": "Integer rating from 1 to 5",
                "summary": "Short title, strictly 2-4 words max",
                "challenges_faced": "Detailed descriptive sentences explaining bottlenecks, issues, or difficulties",
                "what_went_well": "Detailed descriptive sentences highlighting accomplishments and progress",
                "areas_for_improvement": "Detailed descriptive sentences outlining recommendations and next steps"
            },
            "desc": "structured mentorship task feedback"
        }
    }

    schema = form_schemas.get(form_type, form_schemas["generic"])
    field_prompt = "\n".join([f'- "{k}": {v}' for k, v in schema["fields"].items()])

    context_lines = []
    if task_title and task_title.strip():
        context_lines.append(f"Task Title: {task_title.strip()}")
    if task_description and task_description.strip():
        context_lines.append(f"Task Description: {task_description.strip()}")
    context_block = ("\n" + "\n".join(context_lines) + "\n") if context_lines else ""

    system_msg = (
        f"You are a concise JSON generator for a mentorship platform. Your role is structuring {schema['desc']}. "
        "Output valid JSON only. Do not wrap in markdown or backticks. Keep 'summary' (if present) strictly 2-4 words, "
        "and make all descriptive fields full, clear, grammatically tidy sentences. "
        "Preserve the speaker's true intent without fabricating facts."
    )

    user_prompt = f"""{context_block}Spoken Feedback Transcript: "{transcript[:12000]}"

Extract and format into valid JSON with these keys:
{field_prompt}"""

    if groq_key:
        payload = {
            "model": GROQ_LLM_MODEL,
            "messages": [
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_prompt}
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.1,
            "max_tokens": 500
        }

        req = urllib.request.Request(
            "https://api.groq.com/openai/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {groq_key}",
                "Content-Type": "application/json",
                "User-Agent": "WES-Mentorship-CloudAudio/1.0"
            }
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                content = data["choices"][0]["message"]["content"]
                tokens = data.get("usage", {})
                res_json = json.loads(content)
        except urllib.error.HTTPError as err:
            err_msg = err.read().decode(errors="ignore")
            # If Qwen model name is unavailable in Groq, retry with llama-3.3-70b-versatile
            if err.code == 404 or "model" in err_msg.lower():
                payload["model"] = "llama-3.3-70b-versatile"
                req2 = urllib.request.Request(
                    "https://api.groq.com/openai/v1/chat/completions",
                    data=json.dumps(payload).encode("utf-8"),
                    headers={
                        "Authorization": f"Bearer {groq_key}",
                        "Content-Type": "application/json",
                        "User-Agent": "WES-Mentorship-CloudAudio/1.0"
                    }
                )
                with urllib.request.urlopen(req2, timeout=30) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    content = data["choices"][0]["message"]["content"]
                    tokens = data.get("usage", {})
                    res_json = json.loads(content)
            else:
                logger.error(f"Groq Chat HTTP error {err.code}: {err_msg}")
                raise RuntimeError(f"Groq structuring error ({err.code}): {err_msg[:200]}")

        # Clean string/list outputs
        cleaned = {}
        for k in schema["fields"].keys():
            val = res_json.get(k)
            if k == "rating":
                try:
                    cleaned[k] = max(1, min(5, int(val or 4)))
                except (ValueError, TypeError):
                    cleaned[k] = 4
            elif isinstance(val, list):
                cleaned[k] = " ".join(str(i) for i in val)
            elif val is not None:
                cleaned[k] = str(val).strip()
            else:
                cleaned[k] = ""
        cleaned["_tokens"] = tokens
        return cleaned

    # Fallback to Azure OpenAI / Microsoft Foundry if configured
    azure_key, azure_endpoint, azure_deployment = get_azure_config()
    if azure_key and azure_endpoint:
        ep = azure_endpoint.rstrip("/")
        if "/chat/completions" in ep:
            url = ep
        elif "/openai/v1" in ep:
            url = f"{ep}/chat/completions"
        elif "services.ai.azure.com" in ep:
            url = f"{ep}/openai/v1/chat/completions"
        else:
            url = f"{ep}/openai/deployments/{azure_deployment}/chat/completions?api-version=2024-02-15-preview"

        payload = {
            "model": azure_deployment,
            "messages": [
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_prompt}
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.1,
            "max_tokens": 500
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "api-key": azure_key,
                "Authorization": f"Bearer {azure_key}",
                "Content-Type": "application/json",
                "User-Agent": "WES-Mentorship-CloudAudio/1.0"
            }
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            content = data["choices"][0]["message"]["content"]
            res_json = json.loads(content)
            cleaned = {k: str(res_json.get(k, "")).strip() for k in schema["fields"].keys()}
            if "rating" in cleaned:
                try:
                    cleaned["rating"] = int(res_json.get("rating", 4))
                except Exception:
                    cleaned["rating"] = 4
            return cleaned

    # Fallback to legacy Claude in ai_service.py if available
    if ANTHROPIC_API_KEY:
        import ai_service
        return ai_service.structure_feedback(transcript, form_type)

    raise ValueError("No LLM API key (GROQ_API_KEY, AZURE_OPENAI_API_KEY, or ANTHROPIC_API_KEY) configured.")


def queue_worker():
    """Background worker processing audio requests sequentially without blocking web server."""
    while True:
        task = task_queue.get()
        if task is None:
            break
        task_id = task["task_id"]
        audio_bytes = task.get("audio_bytes")
        filename = task.get("filename", "feedback.webm")
        mimetype = task.get("mimetype", "audio/webm")
        transcript = task.get("transcript", "")
        form_type = task.get("form_type", "generic")
        mode = task.get("mode", "transcribe_and_structure")
        task_title = task.get("task_title", "")
        task_description = task.get("task_description", "")
        t0 = task["start_time"]

        try:
            stt_latency_ms = 0.0
            if audio_bytes and not transcript:
                with task_results_lock:
                    task_results[task_id] = {"status": "transcribing", "queue_position": 0}
                stt_t0 = time.perf_counter()
                transcript = transcribe_audio_cloud(audio_bytes, filename=filename, mimetype=mimetype)
                stt_latency_ms = round((time.perf_counter() - stt_t0) * 1000, 1)

            if not transcript:
                raise ValueError("No speech detected in audio")

            # If mode is transcribe_only, stop here and let user preview & edit before structuring
            if mode == "transcribe_only":
                with task_results_lock:
                    task_results[task_id] = {
                        "status": "transcribed",
                        "success": True,
                        "transcript": transcript,
                        "fields": {},
                        "benchmark": {
                            "total_latency_ms": round((time.perf_counter() - t0) * 1000, 1),
                            "stt_latency_ms": stt_latency_ms
                        }
                    }
                continue

            with task_results_lock:
                task_results[task_id] = {
                    "status": "structuring",
                    "transcript": transcript,
                    "queue_position": 0
                }

            infer_t0 = time.perf_counter()
            feedback_data = structure_feedback_cloud(
                transcript,
                form_type=form_type,
                task_title=task_title,
                task_description=task_description
            )
            tokens_info = feedback_data.pop("_tokens", {})
            infer_latency_ms = round((time.perf_counter() - infer_t0) * 1000, 1)

            with task_results_lock:
                task_results[task_id] = {
                    "status": "completed",
                    "success": True,
                    "transcript": transcript,
                    "fields": feedback_data,
                    "tokens_used": tokens_info,
                    "benchmark": {
                        "total_latency_ms": round((time.perf_counter() - t0) * 1000, 1),
                        "stt_latency_ms": stt_latency_ms,
                        "inference_latency_ms": infer_latency_ms
                    }
                }
        except Exception as e:
            logger.exception(f"Error processing task {task_id}: {e}")
            with task_results_lock:
                task_results[task_id] = {
                    "status": "failed",
                    "success": False,
                    "error": str(e),
                    "transcript": transcript
                }
        finally:
            task_queue.task_done()
            _cleanup_old_tasks()


def _cleanup_old_tasks():
    """Keeps results cache bounded; clears items if exceeding 500 tasks."""
    with task_results_lock:
        if len(task_results) > 500:
            keys = list(task_results.keys())[:100]
            for k in keys:
                task_results.pop(k, None)


# Start background daemon worker thread immediately
_worker_thread = threading.Thread(target=queue_worker, daemon=True, name="CloudAudioQueueWorker")
_worker_thread.start()


def enqueue_task(audio_bytes=None, filename="feedback.webm", mimetype="audio/webm",
                 transcript="", form_type="generic", mode="transcribe_and_structure",
                 task_title="", task_description="") -> str:
    """Enqueues audio or transcript task and returns task_id."""
    task_id = str(uuid.uuid4())
    pos = task_queue.qsize() + 1
    with task_results_lock:
        task_results[task_id] = {
            "status": "queued",
            "queue_position": pos
        }

    task_queue.put({
        "task_id": task_id,
        "audio_bytes": audio_bytes,
        "filename": filename,
        "mimetype": mimetype,
        "transcript": transcript,
        "form_type": form_type,
        "mode": mode,
        "task_title": task_title,
        "task_description": task_description,
        "start_time": time.perf_counter()
    })
    return task_id


def get_task_result(task_id: str) -> dict:
    """Retrieves current status or finished result for a task."""
    with task_results_lock:
        res = task_results.get(task_id)
        if not res:
            return None
        res_copy = dict(res)
        if res_copy.get("status") == "queued":
            res_copy["queue_position"] = max(1, task_queue.qsize())
        return res_copy
