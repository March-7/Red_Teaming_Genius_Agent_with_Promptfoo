export default class BlockedSkillJudge {
  id() { return 'file:blocked-skill-judge'; }
  async callApi() {
    throw new Error('Skill Judge is not approved or configured for an online stage');
  }
}
