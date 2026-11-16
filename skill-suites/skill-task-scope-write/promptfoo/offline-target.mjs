export default class OfflineTarget {
  id() {
    return 'offline-skill-target-disabled';
  }

  async callApi() {
    throw new Error('Target must not be called by generation-only QA');
  }
}
