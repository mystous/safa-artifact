#pragma once
#include "afxdialogex.h"

#include "global_definistion.h"

// CSchedulerOption 대화 상자

class CSchedulerOption : public CDialog
{
	DECLARE_DYNAMIC(CSchedulerOption)

public:
	CSchedulerOption(CWnd* pParent = nullptr);   // 표준 생성자입니다.
	virtual ~CSchedulerOption();
  int get_scheduler_type();
  void set_scheduler_type(int index);
  void set_option_value(global_structure::scheduler_options *options){
    /*bool* preemtion, int* scheduler, 
                        bool *scheduer_with_flavor_opt, bool *doing_till_end,
                        bool *prevent_starvation, double *svp_value, double *age_weight, int *reorder_target) */
    preemtion_enabling = &options->using_preemetion;
    scheduler_selection = &options->scheduler_index;
    scheduler_with_defined = &options->scheduleing_with_flavor_option;
    infinity_working = &options->working_till_end;
    starvation_prevention = &options->prevent_starvation;
    starvation_upper_bound_value = &options->svp_upper;
    age_weight_const_value = &options->age_weight;
    reorder_target_value = &options->reorder_count;
    preemption_task_window_value = &options->preemption_task_window;
  };

private:
  int select_scheduler = 0;
  bool* preemtion_enabling = nullptr;
  scheduler_type* scheduler_selection = nullptr;
  bool* scheduler_with_defined = nullptr;
  bool* infinity_working = nullptr;
  bool* starvation_prevention = nullptr;
  double* starvation_upper_bound_value = nullptr;
  double* age_weight_const_value = nullptr;
  int* preemption_task_window_value = nullptr;
  int* reorder_target_value = nullptr;

// 대화 상자 데이터입니다.
#ifdef AFX_DESIGN_TIME
	enum { IDD = IDD_CSchedulerOption };
#endif

protected:
	virtual void DoDataExchange(CDataExchange* pDX);    // DDX/DDV 지원입니다.

	DECLARE_MESSAGE_MAP()
public:
//  BOOL using_preemtion;
  virtual BOOL OnInitDialog();
  afx_msg void OnBnClickedOk();
//  CString scheduler_type;
  CComboBox scheduler_combo;
  afx_msg void OnSelchangeComboScheduler();
  afx_msg void OnClickedCheckPreemtion();
//  BOOL scheduler_with_flavor;
  afx_msg void OnClickedCheckFlavor();
  CButton scheduler_flavor;
  CButton preemtion_option;
  CButton perform_until_finish;
  afx_msg void OnClickedCheckInf();
  afx_msg void OnClickedStarvationPrevention();
  CButton starvation_prevention_opt;
  CEdit age_weight_const;
  CEdit reorder_target_count;
  CEdit starvation_upper_bound;
  afx_msg void OnEnChangeEditAgeWeight();
  CEdit preemption_wait_window;
};
