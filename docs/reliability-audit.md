# OPENARCH reliability audit and development specification

Audit date: 2026-10-29. Scope: the current local application, extraction adapters, browser state, geometry validation, native FreeCAD worker, IFC and drawing exports, storage and publication boundary.

## Assessment

OPENARCH is a working prototype, not yet a general reconstruction system. A plausible render is not evidence that dimensions, topology or balcony access are correct. The present automated extractor recognizes a narrow set of labelled dimensions and vector rectangles. The generic polygon worker has a single eaves height and a flat roof placeholder. The detailed pilot models require additional private interpretation and modelling code; those capabilities must not be described as implemented in the generic application.

The right product direction is an evidence-backed building model with independent reconstruction, review and export stages. FreeCAD is an editable output and geometry engine. It should not be the only place where project identity, evidence and design intent live.

## Defects addressed

| Priority | Defect and consequence | Change / regression coverage |
| --- | --- | --- |
| P1 | Re-analysis could replace manually edited or reviewed geometry; the footprint preservation branch did not protect every field. | Existing geometry is preserved. Re-analysis writes a separate revision-linked proposal, available in the review screen. No automatic build replaces the model from this proposal. |
| P1 | A native timeout could kill a portable launcher while leaving its child CAD process running. Windows `taskkill` also failed in the tested environment. | Windows workers join an owned Job Object before launching the tool; POSIX workers use their own process group. Timeout tests verify that a spawned child stops. Failure requires an exit check and completion marker. |
| P1 | A floor, envelope or access-opening edit could leave dependent balconies marked reviewed. | Server-side dependency invalidation revokes affected review decisions. Unrelated note edits retain review. |
| P1 | Changed source calibration left an old metric footprint usable. | A calibrated trace loses its scale and review state when its source calibration changes. Reapplication is explicit and revisioned. |
| P1 | A single scale could be submitted for an oblique image through the API. | Image-coordinate footprints need an explicit orthographic confirmation before generation. This is a declaration, not an automatic perspective-quality check. Rectification remains unimplemented. |
| P1 | Background responses could restore an older project or saved revision, or erase unsaved editor values. | Request epochs, revision checks, single-flight actions and polling, and dirty-state protection. Switching sections/projects requires saving or explicitly discarding edits. |
| P1 | Saving dimensions discarded edits to openings on the same screen, and a response could erase typing during a save. | Both review buttons save dimensions, levels and openings together. Separate form/JSON edits cannot overwrite each other silently. Editor input is frozen while an action is pending. |
| P1 | Duplicate/overlapping openings and missing access-opening references could generate misleading geometry. | Geometry conflicts block generation; access references must exist and use the same facade. |
| P1 | Unknown or repeated cloud page IDs could silently change which pages were sent. | Validate the exact distinct selection before queueing. Cloud consent resets when changing projects. Cloud output cannot verify itself; invalid footprint-scale citations lose their confidence. |
| P2 | Three conflicting level labels attempted arithmetic on an unresolved value and crashed extraction. | Conflicts remain unresolved without a crash or duplicate note. Centimetres, decimal commas and negative basement levels are recognized. |
| P2 | A duplicate upload could exceed the remaining storage quota even though it should be deduplicated. | Quotas apply to retained unique files; aliases do not consume another source slot. The initial quota snapshot is taken under the project reservation. |
| P2 | A rejected worker submission could leave a project permanently busy. | Submission failure releases the reservation and records a retryable failure. Mutating model operations hold the storage lock through validation and save. |
| P2 | PDFium was opened even when Poppler was selected. | The Poppler route no longer opens the alternative native rasterizer. OCR launches without console-window flashes on Windows. |
| P2 | Sequential opening Booleans created a long recompute chain. | Editable opening tools are combined into one compound cutter. Plan clipping processes individual solids instead of a large all-part Boolean. |
| P2 | Inconsistent polygon face normals can preserve internal seams during coplanar operations. | Native footprint tools use consistent normals and verify one connected face and the expected courtyard topology. Separate native smoke tests cover rectangular and courtyard cases. |
| P2 | Negative basement levels produced floor slabs below a wall shell that started at ground level. | The native wall shell extends to the lowest supplied level. Native readback checks its minimum elevation. |
| P2 | Reopening detailed TechDraw documents could trigger expensive automatic recomputation. | Generated drawing pages are saved with automatic updates off. Update the page explicitly after direct FreeCAD geometry edits. |
| P2 | Validation failures could expose structured provider output in a user-facing exception. | Extraction schema failures use a bounded generic message. |
| P2 | Native backup files were not all covered by ignore patterns. | FreeCAD backup suffixes are ignored; the source-only publication scanner remains the final gate. |

Tests use invented data. Native checks verify solid validity, basement coverage, non-empty drawing views, courtyard count and IFC4 schema validity. They do not establish photographic fidelity, semantic BIM completeness or structural adequacy.

Validation completed locally on Windows: 46 Python unit/API tests, 7 JavaScript state tests, and 2 opt-in native FreeCAD 1.1.4 tests. A fresh synthetic project also completed PDF intake, native CAD/IFC generation, Blender rendering, PDF/CSV packaging and ZIP download verification. Browser checks confirmed persistence across a server restart, combined dimension/opening saves, blocked navigation with unsaved edits, and a separate re-extraction proposal preserving the edited model. A dependency deprecation warning remains in the test client. Live cloud interpretation and live geodata ingestion were not tested. CI is configured for Ubuntu and Windows; native CAD tests require a separate installation.

Windows containment follows Microsoft's documented Job Object inheritance and nested-job mechanism. A small supervisor joins the owned job before starting native tools, avoiding a launch/attachment race. If containment cannot be established, the tool is not started. [Microsoft Job Objects](https://learn.microsoft.com/windows/win32/procthread/job-objects).

## Material gaps still open

| Area | Current limit | Required implementation |
| --- | --- | --- |
| Old drawing interpretation | Named labels and simple rectangles; no general wall extraction or dimension chains. | Segment each sheet into drawing regions; identify title blocks, scales, levels, revisions and dimension chains; deskew scans; retain word/line boxes and OCR confidence. |
| Mixed scales and revisions | One calibration per page and weak date/revision handling. | Region-level coordinate transforms and evidence records. Never fuse incompatible revisions silently. A dimension must cite its source region and anchors. |
| Photographs | No calibrated camera model, rectification or multi-view reconstruction. | Camera intrinsics/extrinsics or measured planar anchors; distortion correction; visibility and occlusion reasoning; cross-view residuals. A homography applies to one plane, not an entire 3D building. |
| Building topology | One polygon shell, common floor levels and a roof placeholder. | Connected wings, per-wing/per-storey outlines and heights, party walls, roof slopes and intersections, dormers, bays and stairs. Validate topology independently from display meshes. |
| Element semantics | Openings are rectangles; two balcony guard types. | Typed wall/opening/door/window/balcony/French-balcony/stair/landing entities with stable IDs, host relationships and existing/proposed/demolished states. |
| Balcony access | An opening reference is not a verified access solution. | Check door threshold, clear opening, door swing, landing, side setbacks, opposing elements and proposed window-to-door conversion. Keep project-specific design rules separate from the modelling kernel. |
| Parametric editing | Some balcony dimensions use native expressions; most envelope interpretation is regeneration-based. | Canonical parameters and dependency graph, deterministic rebuilds, change summaries and controlled native-edit import. Do not silently imply that metadata properties reshape every solid. |
| IFC | Mesh-based exchange representation. | Semantic voids/fillings, storeys, spatial containment, material/property sets and quantities. Keep mesh export as a presentation fallback. |
| Job operations | One local executor and JSON files. | Durable jobs, cancellation, stage checkpoints, bounded logs, recovery and backups; transactional project revisions before collaborative use. |
| Source use | No source-license or attribution registry in the UI. | Record provider, acquisition date, capture date, usage rights, attribution, original asset ID and allowed purpose. Enforce restrictions before reconstruction/export. |
| Measurement assurance | Review flags are user assertions. | Independent anchor checks, uncertainty propagation, transform residuals and benchmarked automatic abstention. |
| Delivery | No general acceptance benchmark. | Private ground-truth corpus, saved reference outputs, geometry/image/schedule comparisons and measured correction time. |

## Source strategy

Use customer-authorized architectural drawings, own photographs and appropriately licensed geodata as reconstruction inputs. Preserve original source hashes and provider metadata outside the public repository.

**Google Earth:** Google's published guidelines prohibit using Earth output to reconstruct 3D models and restrict commercial/promotional imagery use. Do not build an automated Earth-to-building reconstruction feature on the assumption that screenshots grant those rights. Treat legacy Earth-derived geometry as provisional reference work and replace it with permitted evidence before commercial use. [Google Geo Guidelines](https://about.google/brand-resource-center/products-and-services/geo-guidelines/).

**Skråfoto:** prefer the official Dataforsyningen STAC/COG interface to screenshot automation. Its documented metadata includes capture time, camera orientation, perspective centre, horizontal/vertical reference systems, focal length, pixel spacing and principal-point offset. Store these with the asset and transform them into a local millimetre model frame. Use the provider's photogrammetry utilities as a reference implementation, with independent tests of axis/sign conventions. [Official STAC documentation](https://github.com/Klimadatastyrelsen/skraafoto_stac_public/blob/main/dokumentation.md), [official SAUL library](https://github.com/Klimadatastyrelsen/saul).

Dataforsyningen's published terms permit commercial use of the listed free geographic datasets, subject to the applicable conditions. Record the actual asset's terms and attribution; do not infer them from an image URL alone. [Published terms](https://dataforsyningen.dk/asset/PDF/rettigheder_vilkaar/Vilk%C3%A5r%20for%20frie%20geografiske%20data%20og%20CC%20BY%204_0%20licens.pdf).

The viewer warns that measurements starting above terrain can be misleading. Camera data and elevation information matter; a ruler on a roof screenshot does not establish ground dimensions. [Official viewer information](https://skraafoto.dataforsyningen.dk/).

No live geodata integration, account setup or project-address transmission was performed as part of this audit. Service endpoints and authentication must be checked when implementing the adapter.

## Target architecture

1. **Immutable source vault:** original files, hashes, dates, providers, rights and local storage; explicit per-job consent for external processing.
2. **Evidence engine:** page and region detection, vector extraction, Danish OCR, dimension-chain recognition and optional local/cloud vision. Output observations with pixel/world anchors and uncertainty, never direct executable CAD code.
3. **Coordinate graph:** PDF points, scan pixels, rectified planes, geospatial coordinates, vertical datum, local building coordinates and facade coordinates. Every transform has units, anchors, fit residuals and provenance.
4. **Canonical building graph:** site, wings, storeys, walls, roofs, openings and additions. Geometry parameters and element identity are independent of FreeCAD object names.
5. **Reconciliation and review:** explicit contradictions, revision choice, uncertainty overlays and minimal targeted corrections. Re-extraction proposes changes; it does not overwrite accepted work.
6. **Geometry adapters:** deterministic FreeCAD construction, semantic IFC where supported, and a Blender presentation copy. Validate solids, topology and host relationships before packaging.
7. **Feature catalogue:** balconies, French balconies, doors, stairs and landings as typed parametric systems with known supported ranges, dependencies and export mappings.
8. **Acceptance engine:** geometry invariants, source consistency, clash/access checks and private benchmark comparisons. Only reviewed, supported outputs can be issued as ready for the agreed use.

French balconies need a guard-only configuration, not the current projecting slab with a reduced depth. Stairs need riser/tread/landing geometry and host/level relationships. Window-to-door conversion should be a proposed alteration linked to the existing opening, not an unexplained change to the source model. Structural and regulatory approval remain a separate professional workflow.

## Delivery sequence and measurable gates

| Stage | Deliverable | Acceptance gate |
| --- | --- | --- |
| 1. Reliability | The fixes in this audit, clean publication, synthetic and native regressions. | No known silent overwrite; explicit unsupported geometry; bounded workers; reproducible CAD/IFC/drawing checks. |
| 2. Evidence and coordinates | Drawing regions, dimension anchors, immutable revisions, source rights and transform graph. | Independently checked scale on every modelled region; contradictory evidence remains visible. |
| 3. Reconstruction | Wall/opening detection, repeated-storey inference, connected wings and pitched roofs. | Held-out benchmark measures location/size errors, false positives and abstentions separately. |
| 4. Geodata | Official Skråfoto adapter, camera transforms and elevation context. | Multiple independent anchors agree within a documented project tolerance; no silent axis/unit/datum changes. |
| 5. Additions | Doors, French balconies, balconies, stairs and landings with placement/editing tools. | Stable IDs, correct host/level relationships, reproducible schedules and clear existing/proposed state. |
| 6. Product release | Durable jobs, migration, installer, backup and acceptance reports. | Representative end-to-end projects complete reliably on supported hardware; recovery and privacy tests pass. |

Before claiming 90-95%, assemble a private, consented benchmark with independently checked references. A proposed starting set is 40 projects covering clean vectors, degraded scans, mixed scales/revisions, angled courtyard blocks and incomplete photography. This dataset does not exist in the repository today.

Measure field completeness, geometric error distributions, missed/false openings, correct addition assignments, export consistency and total human correction time. Choose tolerances for sales modelling with users before testing. Report unsupported regions and rejected jobs rather than excluding them from the denominator. A review-count percentage is not an accuracy score. The proposed 90-95% target concerns repetitive drafting work saved; it must be demonstrated against measured human baselines.
