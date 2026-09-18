#include "pch.h"
#include "scheduler_mcts.h"
#include <cmath>
#include <algorithm>
#include <limits>
#include <iostream>

scheduler_mcts::scheduler_mcts()
  : root(nullptr), simulation_count(100), exploration_parameter(1.414), rng(std::random_device{}()) {}

scheduler_mcts::~scheduler_mcts() {
  clear_tree();
}

int scheduler_mcts::get_max_schedulable_job(vector<job_entry*>& job_list) {
  int accumulate_request = 0;
  int schedulable_job_count = 0;

  for (auto&& job : job_list) {
    if (accumulate_request + job->get_accelerator_count() > max_assignable_accelerator) {
      break;
    }
    schedulable_job_count++;
    accumulate_request += job->get_accelerator_count();
  }

  return schedulable_job_count;
}

int scheduler_mcts::arrange_server(job_entry& job, int queue_index, accelator_type coprocessor) {
  if (!can_be_scheduled(job.get_accelerator_count(), *target_server, coprocessor)) { return -1; }
  clear_tree();
  root = make_unique<MCTSNode>(nullptr, -1, &job, -1);
  queue_number = queue_index;
  vector<job_entry*> job_list;
  create_job_vector(job_list);
  int max_job_count = get_max_schedulable_job(job_list);

  // TODO : 20 is a magic numbe. It has to be changed into reasonable number or finding exit condition this loop
  for (int i = 0; i < std::min(20*( max_job_count + 1), static_cast<int>(job_list.size())); i++) {
  //for (int i = 0; i < job_list.size(); i++) {
    MCTSNode* node = select_node(root.get());
    expand_node(node, coprocessor);
    double value = simulate(node, job_list, coprocessor);
    backpropagate(node, value);
  }

  int best_server = best_child(root.get());

  if (best_server != -1) {
    server_entry* target = &target_server->at(best_server);
    target->assign_accelator(&job, job.get_accelerator_count());
  }

  return best_server;
}

void scheduler_mcts::postproessing_set_server() {
  // 필요한 초기화 작업 수행
  simulation_count = 100;
  exploration_parameter = 1.414;
}

scheduler_mcts::MCTSNode* scheduler_mcts::select_node(scheduler_mcts::MCTSNode* node) {
  while (!node->children.empty()) {
    node = max_element(node->children.begin(), node->children.end(),
      [=](const unique_ptr<scheduler_mcts::MCTSNode>& a, const unique_ptr<scheduler_mcts::MCTSNode>& b) {
        return calculate_ucb(node, a.get()) < calculate_ucb(node, b.get());
      })->get();
  }
  return node;
}

void scheduler_mcts::expand_node(MCTSNode* node, accelator_type coprocessor) {
  for (size_t i = 0; i < target_server->size(); i++) {
    if (scheduling_with_flavor) {
      /*server_entry server = target_server->at(i);
      accelator_type typet = server.get_accelator_type();*/
      accelator_type typet = target_server->at(i).get_accelator_type();
      if (coprocessor != typet) { continue; }
    }
    if (target_server->at(i).get_avaliable_accelator_count() >= node->job->get_accelerator_count()) {
      node->children.push_back(make_unique<MCTSNode>(node, i, node->job, node->depth + 1));
    }
  }
}

double scheduler_mcts::simulate(MCTSNode* node, vector<job_entry*>& job_list, accelator_type coprocessor) {
  vector<server_entry> simulated_servers = *target_server;
  double total_utilization = 0;
  int allocated_jobs = 0;

  MCTSNode* parent_node = node->parent;

  while (nullptr != parent_node) {
    if (-1 == parent_node->server_index) {
      parent_node = parent_node->parent;
      continue;
    }
    if (-1 != parent_node->depth) {
      simulated_servers[parent_node->server_index].assign_accelator(job_list[parent_node->depth], job_list[parent_node->depth]->get_accelerator_count());
    }
    parent_node = parent_node->parent;
  }
  
  // 임시 서버 목록에 현재까지 트리 노드에 해당하는 서버에 해당 잡들이 할당되었음
  // 시뮬레이션 숫자만큼 반복하면서 남은 잡을 할당하고 가장 높은 점유율을 점수로 주면 됨 (100점으로 노멀라이즈)
  // 총 시뮬레이션(남은 서버에 MC로 잡 넣는 횟수) 당 최대 잡 할당 트라이 수(모드 할당 되면 그 전에 종료)
  uniform_int_distribution<> dist(0, simulated_servers.size() - 1);
  bool no_more_allocated = false;
  int total_accelerator_count = 0;
  for (auto&& server : simulated_servers) {
    total_accelerator_count += server.get_accelerator_count();
  }
  
  double max_allocation = 0.0;
  for (int i = 0; i < simulation_count; i++) {
    int job_list_count = job_list.size();
    vector<server_entry> servers_copy = simulated_servers;
    for (int j = node->depth + 1; j < job_list_count; ++j) {
      if (!can_be_scheduled(job_list[j]->get_accelerator_count(), servers_copy, coprocessor)) { break; }
      int repeat_count = 0;
      do {
        int random_server = dist(rng);
        if (servers_copy[random_server].get_avaliable_accelator_count() >= job_list[j]->get_accelerator_count()) {
          servers_copy[random_server].assign_accelator(job_list[j], job_list[j]->get_accelerator_count());
          break;
        }
        repeat_count++;
      } while (repeat_count < ((job_list_count - node->depth + 1) * 3));
    }

    int allocated_accelrator_count = 0;
    for (auto&& server : servers_copy) {
      allocated_accelrator_count += (server.get_accelerator_count() - server.get_avaliable_accelator_count());
    }

    double allocation = (double)allocated_accelrator_count / (double)total_accelerator_count;
    if (max_allocation < allocation) { max_allocation = allocation; }
  }

  return max_allocation;
}

bool scheduler_mcts::can_be_scheduled(int accelerator_request, vector<server_entry>& servers_copy, accelator_type coprocessor) {
  max_assignable_accelerator = 0;
  for (auto&& server : servers_copy) {
    if (scheduling_with_flavor) {
      accelator_type typet = server.get_accelator_type();
      if (coprocessor != typet) { continue; }
    }
    max_assignable_accelerator += server.get_avaliable_accelator_count();
    if (server.get_avaliable_accelator_count() >= accelerator_request) { return true; }
  }
  return false;
}

void scheduler_mcts::create_job_vector(vector<job_entry*>& job_list) {
  auto job_queue = *(wait_queue_group->at(queue_number));

  for (int i = 0; i < job_queue.size(); ++i) {
    job_list.push_back(job_queue.front());
    job_queue.pop();
  }
}

void scheduler_mcts::backpropagate(MCTSNode* node, double value) {
  while (node != nullptr) {
    node->visits++;
    node->value += value;
    node = node->parent;
  }
}

int scheduler_mcts::best_child(MCTSNode* node) {
  auto best_child = max_element(node->children.begin(), node->children.end(),
    [](const unique_ptr<MCTSNode>& a, const unique_ptr<MCTSNode>& b) {
      return a->value / a->visits < b->value / b->visits;
    });

  return best_child != node->children.end() ? (*best_child)->server_index : -1;
}

double scheduler_mcts::calculate_ucb(MCTSNode* node, MCTSNode* child) {
  if (child->visits == 0) {
    return (numeric_limits<double>::max)();
  }
  return (child->value / child->visits) +
    exploration_parameter * sqrt(log(node->visits) / child->visits);
}

void scheduler_mcts::clear_tree() {
  root.reset();
}