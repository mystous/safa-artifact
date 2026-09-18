#pragma once
#include <thread>
using namespace std;

class call_back_object
{
public:
  virtual void function_call(thread::id) = 0;
};

