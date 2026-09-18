
// gpu_scheduerView.h : interface of the CgpuscheduerView class
//

#pragma once

#include "call_back_object.h"


class CgpuscheduerView : public CScrollView, public call_back_object
{
protected: // create from serialization only
	CgpuscheduerView() noexcept;
	DECLARE_DYNCREATE(CgpuscheduerView)

// Attributes
public:
	CgpuscheduerDoc* GetDocument() const;

private:
  bool is_buffer_created = false;
  bool is_grapch_dc_created = false;
  CDC graph_dc;
  CBitmap graph_bitmap, * old_bitmap_for_graph = nullptr;


// Operations
public:

// Overrides
public:
	virtual void OnDraw(CDC* pDC);  // overridden to draw this view
	virtual BOOL PreCreateWindow(CREATESTRUCT& cs);
protected:
	virtual BOOL OnPreparePrinting(CPrintInfo* pInfo);
	virtual void OnBeginPrinting(CDC* pDC, CPrintInfo* pInfo);
	virtual void OnEndPrinting(CDC* pDC, CPrintInfo* pInfo);

// Implementation
public:
	virtual ~CgpuscheduerView();
#ifdef _DEBUG
	virtual void AssertValid() const;
	virtual void Dump(CDumpContext& dc) const;
#endif
  virtual void function_call(thread::id) override;


protected:

private:
  void draw_buffer(CDC& dc, const CPoint& start_position, double* allocation_rate, double* utilization_rate,
                  job_emulator& job_emul, const int plot_width, const int plot_height);
  void DrawTotalInfo(CDC& dc, CRect& rect, job_emulator& job_emul, CPoint& start_position);
  void DrawColorText(CDC& dc, CString message, CString highlighted, COLORREF col, CPoint& start_position);
  pair<int, int> DrawGPUInfo(CDC& dc, CRect& rect, job_emulator& job_emul, CPoint& start_position);
  pair<int, int> DrawGPUSingleInfo(CDC& dc, CRect& rect, server_entry& server, CPoint& start_position);
  void DrawTotalAllocationRatio(CDC& dc, CRect& rect, CPoint start_position, int reserved, int total_count);
  void DrawProgress(CDC& dc, CRect& rect, job_emulator& job_emul, CPoint& start_position, int reserved, int total_count);
  CString FormatWithCommas(int value);
  int DrawGPUStatus(CDC& dc, CRect& rect);
  void DrawResult(CDC& dc, CRect& rect, job_emulator& job_emul, CPoint& start_position);
  void StartEmul();
  void SetScrollSize();
  CString BuildMetaInfo(job_emulator& job_emul);
  const int draw_width = 4000;
  const int draw_height = 2000;
  const int scroll_area_hor = 1762;
  int scroll_area_ver = 2000;

// Generated message map functions
protected:
	DECLARE_MESSAGE_MAP()
public:
  afx_msg void OnEmulationStart();
  afx_msg void OnEmulationStop();
  afx_msg void OnEmulationSetting();
  afx_msg void OnEmulationSaveresult();
  afx_msg void OnEmulationPause();
  afx_msg void OnEmulationShowjoblist();
  afx_msg BOOL OnEraseBkgnd(CDC* pDC);
  afx_msg void OnServersettingReloadserverlist();
  afx_msg void OnButtonEmulStart();
  afx_msg void OnButtonEmulPause();
  afx_msg void OnButtonEmulStop();
//  afx_msg void OnFileSaveAs();
  afx_msg void OnHScroll(UINT nSBCode, UINT nPos, CScrollBar* pScrollBar);
  virtual void OnInitialUpdate();
  afx_msg void OnVScroll(UINT nSBCode, UINT nPos, CScrollBar* pScrollBar);
//  afx_msg void OnKeyDown(UINT nChar, UINT nRepCnt, UINT nFlags);
  virtual BOOL PreTranslateMessage(MSG* pMsg);
};

#ifndef _DEBUG  // debug version in gpu_scheduerView.cpp
inline CgpuscheduerDoc* CgpuscheduerView::GetDocument() const
   { return reinterpret_cast<CgpuscheduerDoc*>(m_pDocument); }
#endif

