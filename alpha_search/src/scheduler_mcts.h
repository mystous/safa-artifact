#pragma once
#include "job_scheduler.h"
#include <vector>
#include <memory>
#include <random>

class scheduler_mcts : public job_scheduler {
public:
  scheduler_mcts();
  virtual ~scheduler_mcts();
  virtual int arrange_server(job_entry& job, int queue_index = 0, accelator_type coprocessor = accelator_type::any) override;
protected:
  virtual void postproessing_set_server() override;

private:
  struct MCTSNode {
    vector<unique_ptr<MCTSNode>> children;
    MCTSNode* parent;
    int visits;
    double value;
    int server_index;
    job_entry* job;
    int depth;

    MCTSNode(MCTSNode* parent, int server_index, job_entry* job, int tree_depth)
      : parent(parent), visits(0), value(0), server_index(server_index), job(job), depth(tree_depth) {}
  };

  std::unique_ptr<MCTSNode> root;
  int simulation_count;
  double exploration_parameter;
  std::mt19937 rng;
  int queue_number;
  int max_assignable_accelerator;

  int get_max_schedulable_job(vector<job_entry*>& job_list);
  MCTSNode* select_node(MCTSNode* node);
  void expand_node(MCTSNode* node, accelator_type coprocessor);
  double simulate(MCTSNode* node, vector<job_entry*>& job_list, accelator_type coprocessor);
  void backpropagate(MCTSNode* node, double value);
  int best_child(MCTSNode* node);
  double calculate_ucb(MCTSNode* node, MCTSNode* child);
  void create_job_vector(vector<job_entry*> &job_list);
  void clear_tree();
  bool can_be_scheduled(int accelerator_request, vector<server_entry>& servers_copy, accelator_type coprocessor);
};