
// gpu_scheduerDoc.h : interface of the CgpuscheduerDoc class
//


#pragma once

#include "job_emulator.h"


class CgpuscheduerDoc : public CDocument
{
protected: // create from serialization only
	CgpuscheduerDoc() noexcept;
	DECLARE_DYNCREATE(CgpuscheduerDoc)

// Attributes
private:
  job_emulator job_emulator_obj;
  void save_result();
  void generation_task();

// Operations
public:
  job_emulator& get_job_element_obj() {
    return job_emulator_obj;
  };
// Overrides
public:
	virtual BOOL OnNewDocument();
//	virtual void Serialize(CArchive& ar);
#ifdef SHARED_HANDLERS
	virtual void InitializeSearchContent();
	virtual void OnDrawThumbnail(CDC& dc, LPRECT lprcBounds);
#endif // SHARED_HANDLERS

// Implementation
public:
	virtual ~CgpuscheduerDoc();
#ifdef _DEBUG
	virtual void AssertValid() const;
	virtual void Dump(CDumpContext& dc) const;
#endif

protected:

// Generated message map functions
protected:
	DECLARE_MESSAGE_MAP()


#ifdef SHARED_HANDLERS
	// Helper function that sets search content for a Search Handler
	void SetSearchContent(const CString& value);
#endif // SHARED_HANDLERS
public:
  virtual BOOL OnOpenDocument(LPCTSTR lpszPathName);
  virtual BOOL OnSaveDocument(LPCTSTR lpszPathName);
  afx_msg void OnGpuserversettingShowgpulist();
//  afx_msg void OnGpuserversettingAddgpu();
  afx_msg void OnBnClickedButtonAdd();
  afx_msg void OnServersettingReloadserverlist();
  bool ReloadServerList();
  void callback();
  afx_msg void OnFileSaveAs();
  afx_msg void OnFileSave();
};
