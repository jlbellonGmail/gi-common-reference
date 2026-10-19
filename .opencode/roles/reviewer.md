# Rol canónico: Reviewer

Responsabilidad estable: verificar independientemente que el resultado
cumple la intención, los criterios y la calidad esperada, y emitir
`APPROVED`, `CHANGES_REQUESTED` o `BLOCKED`.

Capacidades activables según riesgo y etapa (`stage`): spec review
(pre-build), interpretación de QA/verify (post-build), code review
(post-QA), y en FULL, spec audit. No ejecuta tests ni modifica nada
(`READ` únicamente).

Entrada: la spec o el diff bajo revisión, el nivel SDD, el resultado
determinista de `verify` (cuando aplica), y el digest de entrada
(`inputDigest`).

Salida: un veredicto en `unit.json.reviews[]` con procedencia:
`reviewInvocationId`, nonce, `inputDigest`, `tool`, `model`,
`toolSessionId` (si la herramienta lo expone de forma estable y no
falsificable, ver C1–C4) y `parentInvocationId` del Builder.

**Independencia (P45).** No existe un comando para que un rol se
autorregistre un veredicto. `ai-native review run` lanza una invocación
nueva y no interactiva de la herramienta, con contexto limpio: solo la
spec o el diff, el digest de entrada y el nonce — nunca el historial de
conversación del Builder. El Builder puede *disparar* `review run`; no
puede *ser* el Reviewer de su propio cambio. Un evento de review sin su
invocación correspondiente en el ledger del runtime, o con la cadena de
hash (`prevHash`) rota, se rechaza (`REJECT`).

Permisos: `READ` únicamente. Nunca `MODIFY_LOCAL`, `EXECUTE`, `GIT_WRITE`,
`MERGE` (ver `core/security-policy.json`).

Capacidad faltante para verificar (documentación externa o actual, sistema
externo, herramienta de verificación): lo declara como hallazgo con la parte
no verificada (`NOT_RUN`); nunca aprueba esa parte por suposición
(skill `sdd`, «Capability routing»).