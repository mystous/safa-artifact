#pragma once
#include <chrono>
#include <string>
#include "enum_definition.h"

using namespace std;
using namespace std::chrono;

class utility_class
{
public:
  static system_clock::time_point parse_time_string(const string& time_str);
  static system_clock::time_point get_time_after(const system_clock::time_point start, int min);
  static system_clock::time_point get_time_after(const string& time_str, int min);
  static string conver_tp_str(const system_clock::time_point tp);
  static string get_elapsed_time(system_clock::time_point tp);
  static string double_to_string(double value);
  static string get_accelerator_name(accelator_type type);
  static string format_duration(chrono::seconds duration);
};

