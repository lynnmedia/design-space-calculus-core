language dsc 0.1
target DSC-IR-v0.1

invention SimpleSorter {
  problem {
    need organization:
      actual "small objects are mixed in one tray"
      desired "small objects are separated into labeled sections"

    function separate
    constraint no_power = true
    resource divider
  }

  search {
    seed base
  }
}
