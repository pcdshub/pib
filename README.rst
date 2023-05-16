===
pib
===

.. image:: https://img.shields.io/pypi/v/pib.svg
        :target: https://pypi.python.org/pypi/pib

`Documentation <https://pcdshub.github.io/pib/>`_

``pib`` has a primary goal of migrating existing PCDS IOCs into containerized
versions of themselves: entirely independent of our shared filesystem of
packages.

Name
----

Prototype IOC building (pib) tools for containerization.

Or perhaps: PCDS IOC Building tools (pib) for containerization.

Features
--------

* whatrecord-backed Makefile introspection for dependency detection and build
  order determination
* Simple yaml specification format for epics-base, module, and IOC requirements
* Detect, download/clone, and build missing dependencies for modules and IOCs.
* System package build/run requirements, and patch support.
* click-based command-line interface with fine-grained control over the build
  procedure (separate steps: ``download``, ``build``, ``release_site``,
  ``patch``, ``sync``, ``requirements``, ``parse``, ``inspect``, ...) along
  with a cross-fingers-and-just-do-the-build-thing mode (``pib please``).
* Ability to "lock" IOC module versions to standard releases while still
  allowing for additional modules to be built on top. For example, containers
  may provide fixed versions of asyn that IOCs must be compiled against, and pib
  will pick that version regardless of the IOC's specified version.  If
  additional non-standard modules that rely on asyn - e.g., ``motor`` --
  are marked as IOC dependencies, pib will be flexible about the version of
  that module but fix that module's inclusion of ``asyn``.
  This is an optional experimental approach that attempts to reduce variability
  in module versions. It is possible to disable the behavior by beginning
  with only epics-base (and no standard module versions on top).

Notes
-----

* This is not meant to be run on psbuild-rhel7 or other shared nodes.  While
  technically it will work, there are parts of the build process in pib that
  could modify shared files such as the base-global ``RELEASE_SITE``.  We don't
  want this tool to get in the way of normal operations, so **please** don't
  use it there.
* There are some pre-configured/baked in assumptions about PCDS systems
  currently.  If there is external interest (however doubtful that may be),
  these could be made customizable.
* ``pib`` is intended to work on minimally provisioned OS images.  Dependencies
  which are not available on supported package managers (yum, apt, conda) and
  which do not support the EPICS build system must be pre-installed externally.
  For PCDS, that means things like the startup script templating system.

Future?
-------

Maybe on the list of things to explore:

* Tools for assembling IOCs from scratch, including Jinja-converted
  makeBaseApp templates that can use ``cookiecutter`` and a tool to add
  modules as needed.
* Introspect modules for system library dependencies, with site config
  mapping of library name to system package name.
* Site configuration-defined dependencies (maybe simple ``git clone`` ones as
  well?)
* Support spec file repositories from GitHub such that you could do ``pib -s
  pcdshub/ecs-pib-spec:R7.0.2-23.05-1/base.yaml``.  (aside: This syntax seems
  the most familiar when coming from docker, though it conflicts a bit with the
  environment variable setting of spec files.)
* CI-focused helpers: make it easier for ``pib`` to be used easily in CI jobs
  exclusive of docker.  Along with an appropriate spec file for epics-base (at
  minimum), the goal would be to make the simple ``pib please --app .`` be a
  single-command IOC builder.

Requirements
------------

* Python 3.9+
* apischema
* click
* pyyaml
* whatrecord
* typing_extensions

Installation
------------

::

  $ pip install pib

`PyPI <https://pypi.org/project/pib/>`_

Running the Tests
-----------------
::

  $ python -m pytest -v
