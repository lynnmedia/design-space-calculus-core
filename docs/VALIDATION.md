# Software validation and evidence limits

This public preview supports Python 3.12 only. Its final artifact qualification is recorded with the immutable release. Other interpreter versions are outside this preview's support statement.

An earlier exact DSC bounded candidate was installed on Python 3.11–3.14; each environment passed the bundled success, controlled-failure, and Novum importer checks and all three bundled tests. The subsequent attribution revision kept the stable source code byte identical, built twice into identical artifacts, and passed a fresh Python 3.12.14 installation and the three tests. This bounded package changes release-facing metadata and prose, retaining those same stable source bytes.

The source regression suites passed on Python 3.14.3: 99 core, 6 DSC-SC, 5 interoperability, and 14 IC-012 smoke/synthetic tests. The IC-012 benchmark was not run as a package test. See the versioned release record for exact public archive and wheel hashes, build environment, and final installation qualification.

These tests establish bounded parsing, compilation, validation, controlled failures, workspace initialization, and importer accounting for tested builds. They do not establish invention efficacy, solution quality, novelty, a transformation advantage, or generalization. `novum-dsc/0.1` compatibility is bounded software interoperability, not full semantic equivalence.
